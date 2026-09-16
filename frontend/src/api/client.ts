import type { Actor, Bot, BotInput, InboxItem, Message, ProvidersOut, Run, RunDetail, Thread, ThreadDetail, ThreadUsage, ToolInfo } from "./types";

export const BASE = "/api/v1";
const KEY = "openbot_api_key";
export const getApiKey = (): string => { try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; } };
export const setApiKey = (k: string) => { try { if (k) localStorage.setItem(KEY, k); else localStorage.removeItem(KEY); } catch { /* ignore */ } };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;
  let body: BodyInit | undefined;
  if (init.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(init.json); }
  const r = await fetch(BASE + path, { ...init, headers, body });
  if (r.status === 401) window.dispatchEvent(new CustomEvent("openbot:unauthorized"));
  if (!r.ok) throw new ApiError(r.status, (await r.text()) || r.statusText);
  return r.status === 204 ? (undefined as T) : r.json();
}

export const Api = {
  listBots: () => api<Bot[]>("/bots"),
  getBot: (id: string) => api<Bot>(`/bots/${id}`),
  createBot: (b: BotInput) => api<Bot>("/bots", { method: "POST", json: b }),
  updateBot: (id: string, b: Partial<BotInput>) => api<Bot>(`/bots/${id}`, { method: "PATCH", json: b }),
  deleteBot: (id: string) => api<void>(`/bots/${id}`, { method: "DELETE" }),
  listActors: () => api<Actor[]>("/actors"),
  createActor: (a: { handle: string; name: string; description?: string; webhook_url?: string | null; webhook_secret?: string | null }) => api<Actor>("/actors", { method: "POST", json: a }),
  deleteActor: (id: string) => api<void>(`/actors/${id}`, { method: "DELETE" }),
  listThreads: () => api<Thread[]>("/threads"),
  createThread: (t: { title?: string; handles: string[]; default_bot_handle?: string; working_directory?: string | null }) => api<Thread>("/threads", { method: "POST", json: t }),
  getThread: (id: string, before?: string) => api<ThreadDetail>(`/threads/${id}?limit=50${before ? `&before=${before}` : ""}`),
  deleteThread: (id: string) => api<void>(`/threads/${id}`, { method: "DELETE" }),
  updateThread: (id: string, body: { default_bot_handle: string }) => api<Thread>(`/threads/${id}`, { method: "PATCH", json: body }),
  postMessage: (id: string, body: { content: string; to?: string[] }) => api<{ message: Message; addressed: string[]; unaddressed: boolean }>(`/threads/${id}/messages`, { method: "POST", json: body }),
  ackThread: (id: string) => api<{ acked: number }>(`/threads/${id}/ack`, { method: "POST" }),
  listInbox: () => api<InboxItem[]>("/inbox"),
  ackItem: (id: string) => api<InboxItem>(`/inbox/${id}/ack`, { method: "POST" }),
  listRuns: (threadId: string) => api<Run[]>(`/runs?thread_id=${threadId}`),
  getRun: (id: string) => api<RunDetail>(`/runs/${id}`),
  getThreadUsage: (id: string) => api<ThreadUsage>(`/threads/${id}/usage`),
  resumeRun: (id: string, body: { answer?: string; decisions?: ("approve" | "reject")[] }) => api<Run>(`/runs/${id}/resume`, { method: "POST", json: body }),
  cancelRun: (id: string) => api<Run>(`/runs/${id}/cancel`, { method: "POST" }),
  listTools: () => api<{ tools: ToolInfo[]; errors: { file: string; error: string }[] }>("/tools"),
  getProviders: () => api<ProvidersOut>("/providers"),
};
