import type { BusEvent, Message, Run, RunDetail, RunEvent, ThreadDetail, Waiter } from "../api/types";

export interface ThreadState { threadId?: string; messages: Message[]; runs: Record<string, Run>; runEvents: Record<string, RunEvent[]>; streaming: Record<string, string>; waiters: Waiter[]; }

export const emptyThreadState = (threadId?: string): ThreadState => ({ threadId, messages: [], runs: {}, runEvents: {}, streaming: {}, waiters: [] });

const sortMsgs = (ms: Message[]) => [...ms].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));

export function hydrate(state: ThreadState, detail: ThreadDetail): ThreadState {
  const byId = new Map(state.messages.map((m) => [m.id, m]));
  detail.messages.forEach((m) => byId.set(m.id, m));
  const runs = { ...state.runs };
  detail.runs.forEach((r) => (runs[r.id] = r));
  // detail.waiters is optional so a page rendered against an older backend degrades to "no waiters".
  return { ...state, messages: sortMsgs([...byId.values()]), runs, waiters: detail.waiters ?? [] };
}

/**
 * Fold a run fetched on demand (GET /runs/{id}) into the thread. `GET /threads/{id}`
 * only returns *open* runs, so a completed run reached this way is the only copy we
 * have and must be kept in `runs` — otherwise its card would vanish as soon as the
 * query that produced it is dropped. Idempotent: an existing run came from SSE and is
 * at least as fresh, and events are merged by id.
 */
export function mergeRun(state: ThreadState, detail: RunDetail): ThreadState {
  const { events, ...run } = detail;
  const byId = new Map((state.runEvents[run.id] ?? []).map((e) => [e.id, e]));
  events.forEach((e) => byId.set(e.id, e));
  return {
    ...state,
    runs: { ...state.runs, [run.id]: state.runs[run.id] ?? run },
    runEvents: { ...state.runEvents, [run.id]: [...byId.values()].sort((a, b) => a.seq - b.seq) },
  };
}

export function reduceThreadEvent(state: ThreadState, e: BusEvent): ThreadState {
  switch (e.event) {
    case "message.created": {
      if (state.messages.some((m) => m.id === e.data.id)) return state;
      return { ...state, messages: sortMsgs([...state.messages, e.data]) };
    }
    case "run.updated": {
      const run: Run = e.data;
      const streaming = { ...state.streaming };
      if (run.status !== "running") delete streaming[run.id];
      return { ...state, runs: { ...state.runs, [run.id]: run }, streaming };
    }
    case "waiters.updated":
      // Same thread only: the SSE subscription filters, but the reducer is also the last line of
      // defense for events that reach it from anywhere else.
      return e.thread_id === state.threadId ? { ...state, waiters: e.data?.waiters ?? [] } : state;
    case "run.event": {
      const d = e.data;
      if (d.type === "text_delta") {
        return { ...state, streaming: { ...state.streaming, [d.run_id]: (state.streaming[d.run_id] ?? "") + d.payload.delta } };
      }
      const list = state.runEvents[d.run_id] ?? [];
      if (list.some((x) => x.id === d.id)) return state;
      const streaming = { ...state.streaming };
      if (d.type === "text") delete streaming[d.run_id];
      return { ...state, runEvents: { ...state.runEvents, [d.run_id]: [...list, d].sort((a, b) => a.seq - b.seq) }, streaming };
    }
    default:
      return state;
  }
}
