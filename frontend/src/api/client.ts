import type { Actor, AppSetting, Bot, BotCatalogEntry, DirectoryListing, McpCatalogEntry, McpConnectResult, McpServer, McpServerInput, BotInboxItem, BotInput, BotMemory, InboxItem, Message, ModelsOut, ProvidersOut, PurgeResult, Run, RunDetail, SetupStatus, Thread, ThreadDetail, ThreadUsage, ToolInfo, DatabaseLocation } from "./types";

/** Outgoing attachment for postMessage: a data URL plus an optional display name. */
export interface ScheduledMessage { id: string; thread_id: string; content: string; due_at: string; status: string; attempts: number; last_error?: string | null; result_message_id?: string | null; to_handles: string[]; }

export interface AttachmentIn { url: string; name?: string; }
import { ApiError, backendUnavailableEvent, isBackendUnavailable } from "./errors";

export { ApiError } from "./errors";

declare global {
  interface Window {
    openbotDesktop?: { isElectron: boolean };
  }
}

export const BASE = "/api/v1";
const KEY = "openbot_api_key";
const ACTOR = "openbot_actor_handle";
export const getApiKey = (): string => { try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; } };
export const getActorHandle = (): string => { try { return localStorage.getItem(ACTOR) ?? "you"; } catch { return "you"; } };
export const setApiKey = (k: string) => { if (k) localStorage.setItem(KEY, k); else localStorage.removeItem(KEY); window.dispatchEvent(new Event("openbot:api-key-changed")); };

async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;
  if (path === "/scheduled" || path.startsWith("/scheduled/")) headers["X-OpenBot-Actor"] = getActorHandle();
  let body: BodyInit | undefined;
  if (init.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(init.json); }
  let r: Response;
  try { r = await fetch(BASE + path, { ...init, headers, body }); }
  catch (err) { if (err instanceof TypeError) window.dispatchEvent(new CustomEvent(backendUnavailableEvent)); throw err; }
  if (r.status === 401) window.dispatchEvent(new CustomEvent("openbot:unauthorized"));
  if (!r.ok) { const text = await r.text().catch(() => ""); const err = new ApiError(r.status, text || r.statusText); if (isBackendUnavailable(err)) window.dispatchEvent(new CustomEvent(backendUnavailableEvent)); throw err; }
  return r.status === 204 ? (undefined as T) : r.json();
}

export const Api = {
  listBots: () => api<Bot[]>("/bots"),
  listBotCatalog: () => api<BotCatalogEntry[]>("/bots/catalog"),
  installBotCatalogEntry: ({ id, handle }: { id: string; handle?: string }) => api<Bot>(`/bots/catalog/${id}/install`, { method: "POST", json: handle ? { handle } : {} }),
  getBot: (id: string) => api<Bot>(`/bots/${id}`),
  createBot: (b: BotInput) => api<Bot>("/bots", { method: "POST", json: b }),
  updateBot: (id: string, b: Partial<BotInput>) => api<Bot>(`/bots/${id}`, { method: "PATCH", json: b }),
  deleteBot: (id: string) => api<void>(`/bots/${id}`, { method: "DELETE" }),
  getBotInbox: (id: string) => api<BotInboxItem[]>(`/bots/${id}/inbox`),
  postBotInbox: (id: string, content: string) => api<BotInboxItem>(`/bots/${id}/inbox`, { method: "POST", json: { content } }),
  purgeBot: (id: string) => api<PurgeResult>(`/bots/${id}/purge`, { method: "POST" }),
  listBotMemories: (id: string) => api<BotMemory[]>(`/bots/${id}/memories`),
  deleteBotMemory: (id: string, key: string) => api<void>(`/bots/${id}/memories/${encodeURIComponent(key)}`, { method: "DELETE" }),
  listActors: () => api<Actor[]>("/actors"),
  createActor: (a: { handle: string; name: string; description?: string; webhook_url?: string | null; webhook_secret?: string | null }) => api<Actor>("/actors", { method: "POST", json: a }),
  deleteActor: (id: string) => api<void>(`/actors/${id}`, { method: "DELETE" }),
  listThreads: () => api<Thread[]>("/threads"),
  createThread: (t: { title?: string; handles: string[]; default_bot_handle?: string; working_directory?: string | null }) => api<Thread>("/threads", { method: "POST", json: t }),
  getThread: (id: string, before?: string) => api<ThreadDetail>(`/threads/${id}?limit=50${before ? `&before=${before}` : ""}`),
  deleteThread: (id: string) => api<void>(`/threads/${id}`, { method: "DELETE" }),
  updateThread: (id: string, body: { default_bot_handle: string }) => api<Thread>(`/threads/${id}`, { method: "PATCH", json: body }),
  postMessage: (id: string, body: { content: string; to?: string[]; attachments?: AttachmentIn[] }) => api<{ message: Message; addressed: string[]; unaddressed: boolean }>(`/threads/${id}/messages`, { method: "POST", json: body }),
  ackThread: (id: string) => api<{ acked: number }>(`/threads/${id}/ack`, { method: "POST" }),
  listInbox: () => api<InboxItem[]>("/inbox"),
  ackItem: (id: string) => api<InboxItem>(`/inbox/${id}/ack`, { method: "POST" }),
  listRuns: (threadId: string) => api<Run[]>(`/runs?thread_id=${threadId}`),
  getRun: (id: string) => api<RunDetail>(`/runs/${id}`),
  getThreadUsage: (threadId: string) => api<ThreadUsage>(`/threads/${threadId}/usage`),
  listDirectories: (path: string) => api<DirectoryListing>(`/workspace/directories?path=${encodeURIComponent(path || ".")}`),
  resumeRun: (id: string, body: { answer?: string; decisions?: ("approve" | "reject")[] }) => api<Run>(`/runs/${id}/resume`, { method: "POST", json: body }),
  cancelRun: (id: string) => api<Run>(`/runs/${id}/cancel`, { method: "POST" }),
  listTools: () => api<{ tools: ToolInfo[]; errors: { file: string; error: string }[] }>("/tools"),
  listMcpServers: () => api<McpServer[]>("/mcp/servers"),
  listMcpCatalog: () => api<McpCatalogEntry[]>("/mcp/catalog"),
  installMcpCatalogEntry: (id: string, body: { name: string; env?: Record<string, string>; enabled?: boolean }) => api<McpServer>(`/mcp/catalog/${id}/install`, { method: "POST", json: body }),
  addMcpServer: (body: McpServerInput) => api<McpServer>("/mcp/servers", { method: "POST", json: body }),
  updateMcpServer: (name: string, body: McpServerInput) => api<McpServer>(`/mcp/servers/${name}`, { method: "PATCH", json: body }),
  removeMcpServer: (name: string) => api<void>(`/mcp/servers/${name}`, { method: "DELETE" }),
  connectMcpServer: (name: string) => api<McpConnectResult>(`/mcp/servers/${name}/connect`, { method: "POST" }),
  disconnectMcpServer: (name: string) => api<McpServer>(`/mcp/servers/${name}/disconnect`, { method: "POST" }),
  forgetMcpCredentials: (name: string) => api<McpServer>(`/mcp/servers/${name}/credentials`, { method: "DELETE" }),
  getSetupStatus: () => api<SetupStatus>("/setup/status"),
  getSettings: () => api<AppSetting[]>("/settings"),
  getDatabaseLocation: () => api<DatabaseLocation>("/settings/database-location"),
  patchSettings: (updates: Record<string, unknown>) => api<AppSetting[]>("/settings", { method: "PATCH", json: updates }),
  resetSetting: (key: string) => api<AppSetting[]>(`/settings/${key}`, { method: "DELETE" }),
  listScheduled: () => api<ScheduledMessage[]>("/scheduled"),
  createScheduled: (body: { thread_id: string; content: string; due_at: string; to: string[] }) => api<ScheduledMessage>("/scheduled", { method: "POST", json: body }),
  cancelScheduled: (id: string) => api<ScheduledMessage>(`/scheduled/${id}/cancel`, { method: "POST" }),
  getProviders: () => api<ProvidersOut>("/providers"),
  getModels: (provider: string) => api<ModelsOut>(`/models?provider=${encodeURIComponent(provider)}`),
};
