// @vitest-environment jsdom
// React 19: act() must know it runs in a test environment (no RTL here to set it for us).
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ThreadPage from "./ThreadPage";
import type { Bot, Message, Run, ThreadDetail } from "../api/types";
import { clearThreadDraft } from "../lib/threadDrafts";

// SSE is replaced wholesale: the page only consumes callbacks, and jsdom has no EventSource.
// Capturing them lets a test inject live events as if they came off the bus.
const sse = vi.hoisted(() => ({
  onEvent: null as null | ((e: unknown) => void),
  onReconnect: null as null | (() => void),
}));
vi.mock("../api/sse", () => ({
  useBusEvents: (_id: string, onEvent: (e: unknown) => void, onReconnect?: () => void) => {
    sse.onEvent = onEvent;
    sse.onReconnect = onReconnect ?? null;
  },
}));

// A mutable fake Api so a test can change what the backend would answer mid-flight.
const fake = vi.hoisted(() => ({ api: {} as Record<string, (...args: never[]) => unknown> }));
vi.mock("../api/client", () => ({ Api: fake.api }));

const msg = (id: string, content: string, at: string, runId: string | null = null): Message =>
  ({ id, thread_id: "t1", sender_actor_id: null, sender_kind: "bot", sender_name: "Bot", content, mentions: [], hop: 0, run_id: runId, metadata: {}, created_at: at });
const run = (id: string, status: string): Run =>
  ({ id, actor_id: "b1", thread_id: "t1", status, interrupt: null, error: null, langsmith_run_id: null, created_at: "2026-01-01T00:00:00Z", started_at: null, finished_at: null });
// What the backend says about r1; GET /threads/{id} lists it only while it is open.
const runStatus: Record<string, string> = {};
const OPEN = ["queued", "running", "waiting_human"];
const detail = (id: string, messages: Message[], hasMore = false): ThreadDetail =>
  ({
    id, title: `title-${id}`, kind: "chat", created_by_actor_id: null, default_bot_actor_id: null, default_bot_handle: null,
    working_directory: null, external_ref: null, created_at: "", updated_at: "", last_message_at: null,
    participants: [], messages, has_more: hasMore, runs: OPEN.includes(runStatus.r1) ? [run("r1", runStatus.r1)] : [], waiters: [],
  }) as ThreadDetail;

const m1 = msg("m1", "first reply", "2026-01-01T00:00:01Z", "r1");
const m2 = msg("m2", "reply posted while away", "2026-01-01T00:00:02Z");
const m3 = msg("m3", "live after return", "2026-01-01T00:00:03Z");
const toolCall = { id: "e-tool", run_id: "r1", seq: 0, type: "tool_call", payload: { name: "shell", args: { command: "echo preserved" }, id: "call-1" }, created_at: "2026-01-01T00:00:01Z" } as const;

describe("ThreadPage window re-entry", () => {
  let root: Root;
  let el: HTMLDivElement;
  let qc: QueryClient;
  let getThreadCalls: string[];
  // Append-only fake backend: what GET /threads/{id} would answer, per thread. A message the
  // bus published is persisted first (see delivery), so once it is emitted it stays in every
  // later response — the fake must behave the same way or it manufactures bugs.
  let server: Record<string, Message[]>;
  const navRef: { current: null | ((to: string) => void) } = { current: null };

  const text = (): string => el.textContent ?? "";
  const textarea = (): HTMLTextAreaElement => el.querySelector("textarea")!;
  const type = async (value: string): Promise<void> => {
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea(), value);
      textarea().setSelectionRange(value.length, value.length);
      textarea().dispatchEvent(new Event("input", { bubbles: true }));
    });
  };
  const until = async (cond: () => boolean, what: string): Promise<void> => {
    const deadline = Date.now() + 2_000;
    while (!cond()) {
      if (Date.now() > deadline) throw new Error(`timeout waiting for ${what}; page text: ${text().slice(0, 300)}`);
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    }
  };
  const t1Calls = (): number => getThreadCalls.filter((c) => c === "t1").length;
  // ThreadPage reads the thread id from the router, so window switches are driven through the
  // router itself: another thread window is just another route, like in the real app.
  const App = () => {
    const navigate = useNavigate();
    useEffect(() => { navRef.current = navigate; }, [navigate]);
    return (
      <Routes>
        <Route path="/threads/:id" element={<ThreadPage />} />
        <Route path="/other" element={<div>other window</div>} />
      </Routes>
    );
  };
  const mount = async (path: string): Promise<void> => {
    await act(async () => {
      root.render(
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={[path]}>
            <App />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });
  };
  const go = async (path: string): Promise<void> => { await act(async () => { navRef.current?.(path); }); };

  beforeEach(() => {
    clearThreadDraft("t1");
    clearThreadDraft("t2");
    Element.prototype.scrollTo = () => {};
    getThreadCalls = [];
    server = { t1: [m1], t2: [] };
    runStatus.r1 = "running";
    fake.api.getThread = (id: string) => {
      getThreadCalls.push(id);
      return Promise.resolve(detail(id, [...(server[id] ?? [])])) as never;
    };
    fake.api.getThreadUsage = () => Promise.resolve({ model_calls: 0, prompt_tokens: 0, completion_tokens: 0, cache_read_tokens: 0 }) as never;
    fake.api.listBots = () => Promise.resolve([{ id: "b1", name: "Bot", icon: null } as unknown as Bot]) as never;
    fake.api.ackThread = () => Promise.resolve({ acked: 0 }) as never;
    fake.api.getRun = (id: string) => Promise.resolve({ ...run(id, runStatus[id] ?? "running"), events: [] }) as never;
    qc = new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: false } } });
    el = document.createElement("div");
    document.body.appendChild(el);
    root = createRoot(el);
  });
  // A page left mounted keeps its window Esc listener, which would cancel runs in later tests.
  afterEach(() => { act(() => root.unmount()); el.remove(); });

  it("restores each thread's draft after switching away and back", async () => {
    await mount("/threads/t1");
    await until(() => text().includes("first reply"), "initial history");
    await type("draft for t1");
    await go("/threads/t2");
    await until(() => text().includes("title-t2"), "second thread window");
    expect(textarea().value).toBe("");
    await type("draft for t2");
    await go("/threads/t1");
    await until(() => textarea().value === "draft for t1", "t1 draft restored");
    await go("/threads/t2");
    await until(() => textarea().value === "draft for t2", "t2 draft restored");
  });

  it("clears a draft only after sending succeeds", async () => {
    const posted: string[] = [];
    fake.api.postMessage = (_id: string, body: { content: string }) => { posted.push(body.content); return Promise.resolve({ unaddressed: false }) as never; };
    await mount("/threads/t1");
    await until(() => text().includes("first reply"), "initial history");
    await type("send this draft");
    await act(async () => { textarea().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })); });
    await until(() => textarea().value === "", "draft cleared after send");
    expect(posted).toEqual(["send this draft"]);
    await go("/threads/t2");
    await until(() => text().includes("title-t2"), "second thread window");
    await go("/threads/t1");
    await until(() => textarea().value === "", "cleared draft stays cleared");
  });

  it("retains a draft after a failed send and restores it after switching threads", async () => {
    fake.api.postMessage = () => Promise.reject(new Error("send failed")) as never;
    await mount("/threads/t1");
    await until(() => text().includes("first reply"), "initial history");
    await type("retry this draft");
    await act(async () => { textarea().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })); });
    await until(() => textarea().value === "retry this draft", "failed send retains draft");

    await go("/threads/t2");
    await until(() => text().includes("title-t2"), "second thread window");
    await go("/threads/t1");
    await until(() => textarea().value === "retry this draft", "failed draft restored");
  });

  it("restores history after leaving to another window and returning mid-run", async () => {
    await mount("/threads/t1");
    await until(() => text().includes("first reply"), "initial history");
    expect(text()).toContain("first reply");

    // --- away: while the user reads the other window, the bot posts m2 (the backend now
    // serves it, but the closed SSE socket will never replay it).
    await go("/other");
    await until(() => text().includes("other window"), "switched away");
    server.t1 = [...server.t1, m2];

    // --- back on the thread: the reply posted while away must be there too. Waiting on m2
    // (not m1) is the point: m1 alone also renders from the stale cache.
    await go("/threads/t1");
    await until(() => text().includes("reply posted while away"), "history restored");
    expect(text()).toContain("first reply");
    expect(t1Calls()).toBeGreaterThan(1);

    // --- a live update after returning still shows up (AC2); it is persisted server-side too.
    await act(async () => {
      server.t1 = [...server.t1, m3];
      sse.onEvent?.({ event: "message.created", thread_id: "t1", data: m3 });
    });
    await until(() => text().includes("live after return"), "live message after return");

    // --- back and forth again: still exactly one copy of everything (AC3), in order. The
    // SSE-only m3 must survive this fresh fetch too, because hydrate merges instead of replacing.
    await go("/other");
    await until(() => text().includes("other window"), "switched away again");
    await go("/threads/t1");
    await until(() => t1Calls() >= 3, "third fetch of t1");
    await until(() => text().includes("live after return"), "sse-posted message survives refetch");
    expect(text().split("first reply")).toHaveLength(2);
    expect(text().split("reply posted while away")).toHaveLength(2);
    expect(text().split("live after return")).toHaveLength(2);
    const order = [text().indexOf("first reply"), text().indexOf("reply posted while away"), text().indexOf("live after return")];
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("preserves active tool output when switching away and back", async () => {
    await mount("/threads/t1");
    await until(() => text().includes("first reply"), "initial history");

    await act(async () => {
      sse.onEvent?.({ event: "run.event", thread_id: "t1", data: toolCall });
    });
    await until(() => text().includes("echo preserved"), "tool output");

    await go("/other");
    await until(() => text().includes("other window"), "switched away");
    await go("/threads/t1");
    await until(() => text().includes("echo preserved"), "tool output after return");
    expect(text().split("echo preserved")).toHaveLength(2);
  });

  it("restores history when switching directly between two thread windows", async () => {
    await mount("/threads/t1");
    await until(() => text().includes("first reply"), "initial history");

    // --- to the other thread window; while there, the bot posts m2 into t1.
    await go("/threads/t2");
    await until(() => text().includes("title-t2"), "second thread window");
    server.t1 = [...server.t1, m2];

    // --- straight back to t1: m2 must render, not just the cached m1.
    await go("/threads/t1");
    await until(() => text().includes("reply posted while away"), "history restored on direct re-entry");
    expect(text()).toContain("first reply");
    // Exactly one copy of each message, in order (AC3).
    expect(text().split("first reply")).toHaveLength(2);
    expect(text().split("reply posted while away")).toHaveLength(2);
    const order = [text().indexOf("first reply"), text().indexOf("reply posted while away")];
    expect(order[0]).toBeLessThan(order[1]);
  });

  it("does not carry one thread's transcript into another", async () => {
    server.t2 = [msg("m9", "only in t2", "2026-01-01T00:00:09Z")];
    await mount("/threads/t1");
    await until(() => text().includes("first reply"), "initial history");
    await act(async () => {
      sse.onEvent?.({ event: "run.event", thread_id: "t1", data: toolCall });
    });
    await until(() => text().includes("echo preserved"), "tool output");

    await go("/threads/t2");
    await until(() => text().includes("only in t2"), "second thread history");
    expect(text()).not.toContain("first reply");
    expect(text()).not.toContain("echo preserved");
  });

  it("settles a run that finished while the page was away", async () => {
    await mount("/threads/t1");
    await until(() => text().includes("first reply") && text().includes("running"), "open run card");

    // r1 finishes while another window is open, so its run.updated never reaches this page. Coming
    // back restores the cached transcript, and the thread response no longer lists r1 at all.
    await go("/other");
    await until(() => text().includes("other window"), "switched away");
    runStatus.r1 = "completed";
    await go("/threads/t1");
    await until(() => text().includes("completed"), "run card settled");
    expect(text()).not.toContain("running");
  });
});

describe("ThreadPage Esc stops open runs", () => {
  let root: Root;
  let el: HTMLDivElement;
  let cancelled: string[];
  let runs: Run[];

  const text = (): string => el.textContent ?? "";
  const until = async (cond: () => boolean, what: string): Promise<void> => {
    const deadline = Date.now() + 2_000;
    while (!cond()) {
      if (Date.now() > deadline) throw new Error(`timeout waiting for ${what}; page text: ${text().slice(0, 300)}`);
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    }
  };
  const esc = async (target: EventTarget = document.body): Promise<void> => {
    await act(async () => { target.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
  };
  const textarea = () => el.querySelector("textarea")!;
  const type = async (value: string): Promise<void> => {
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea(), value);
      textarea().setSelectionRange(value.length, value.length);
      textarea().dispatchEvent(new Event("input", { bubbles: true }));
    });
  };
  const mount = async (): Promise<void> => {
    const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: false } } });
    await act(async () => {
      root.render(
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={["/threads/t1"]}>
            <Routes><Route path="/threads/:id" element={<ThreadPage />} /></Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });
    await until(() => text().includes("first reply"), "thread loaded");
  };

  beforeEach(() => {
    clearThreadDraft("t1");
    clearThreadDraft("t2");
    Element.prototype.scrollTo = () => {};
    cancelled = [];
    runs = [run("r1", "running"), { ...run("r2", "queued"), actor_id: "b2" }];
    fake.api.getThread = () => Promise.resolve({ ...detail("t1", [m1]), runs }) as never;
    fake.api.getThreadUsage = () => Promise.resolve({ model_calls: 0, prompt_tokens: 0, completion_tokens: 0, cache_read_tokens: 0 }) as never;
    fake.api.listBots = () => Promise.resolve([{ id: "b1", name: "Coder", handle: "coder", enabled: true, icon: null } as unknown as Bot]) as never;
    fake.api.ackThread = () => Promise.resolve({ acked: 0 }) as never;
    fake.api.getRun = (id: string) => Promise.resolve({ ...(runs.find((r) => r.id === id) ?? run(id, "completed")), events: [] }) as never;
    fake.api.cancelRun = (id: string) => { cancelled.push(id); return Promise.resolve(run(id, "cancelled")) as never; };
    el = document.createElement("div");
    document.body.appendChild(el);
    root = createRoot(el);
  });
  afterEach(() => { act(() => root.unmount()); el.remove(); });

  it("cancels every open run in the thread once, and shows the hint while they run", async () => {
    await mount();
    expect(text()).toContain("Esc stop");
    await esc(el.querySelector("textarea")!);
    expect(cancelled.sort()).toEqual(["r1", "r2"]);
    await esc();
    expect(cancelled).toHaveLength(2);
  });

  it("does nothing when no run is open", async () => {
    runs = [];
    await mount();
    expect(text()).not.toContain("Esc stop");
    await esc();
    expect(cancelled).toEqual([]);
  });

  it("leaves Esc to an open menu", async () => {
    await mount();
    await act(async () => { el.querySelector<HTMLButtonElement>('[aria-label="Thread actions"]')!.click(); });
    expect(el.querySelector('[role="menu"]')).not.toBeNull();
    await esc();
    await until(() => el.querySelector('[role="menu"]') === null, "menu closed");
    expect(cancelled).toEqual([]);
  });

  it("closes the mention list first, then stops on the next Esc", async () => {
    await mount();
    const listOpen = () => el.querySelector('[role="listbox"]') !== null;
    await type("@c");
    expect(listOpen()).toBe(true);
    await esc(textarea());
    expect(listOpen()).toBe(false);
    expect(cancelled).toEqual([]);
    await type("@co");
    expect(listOpen()).toBe(false);
    await esc(textarea());
    expect(cancelled.sort()).toEqual(["r1", "r2"]);
  });

  it("offers the mention list again for a new mention after dismissing one", async () => {
    await mount();
    await type("@c");
    await esc(textarea());
    await type("");
    await type("@c");
    expect(el.querySelector('[role="listbox"]')).not.toBeNull();
  });

  it("forgets a dismissed mention list once the draft is sent", async () => {
    fake.api.postMessage = () => Promise.resolve({ unaddressed: false }) as never;
    await mount();
    await type("@c");
    await esc(textarea());
    await act(async () => { textarea().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })); });
    await until(() => textarea().value === "", "draft sent");
    await type("@");
    expect(el.querySelector('[role="listbox"]')).not.toBeNull();
  });
});
