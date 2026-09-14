import { describe, expect, it } from "vitest";
import { emptyThreadState, reduceThreadEvent } from "./threadState";

const msg = (id: string, t: string) => ({ id, thread_id: "t", sender_actor_id: null, sender_kind: "human", sender_name: "You",
  content: "c" + id, mentions: [], hop: 0, run_id: null, metadata: {}, created_at: t });
const run = (id: string, status: string) => ({ id, actor_id: "b", thread_id: "t", status, interrupt: null, error: null,
  langsmith_run_id: null, created_at: "2026-01-01T00:00:00Z", started_at: null, finished_at: null });

describe("threadState", () => {
  it("appends messages once, sorted", () => {
    let s = emptyThreadState();
    s = reduceThreadEvent(s, { event: "message.created", thread_id: "t", data: msg("2", "2026-01-01T00:00:02Z") });
    s = reduceThreadEvent(s, { event: "message.created", thread_id: "t", data: msg("1", "2026-01-01T00:00:01Z") });
    s = reduceThreadEvent(s, { event: "message.created", thread_id: "t", data: msg("1", "2026-01-01T00:00:01Z") });
    expect(s.messages.map((m) => m.id)).toEqual(["1", "2"]);
  });
  it("tracks runs, deltas and events", () => {
    let s = emptyThreadState();
    s = reduceThreadEvent(s, { event: "run.updated", thread_id: "t", data: run("r1", "running") });
    s = reduceThreadEvent(s, { event: "run.event", thread_id: "t", data: { run_id: "r1", type: "text_delta", payload: { delta: "He" } } });
    s = reduceThreadEvent(s, { event: "run.event", thread_id: "t", data: { run_id: "r1", type: "text_delta", payload: { delta: "y" } } });
    expect(s.streaming["r1"]).toBe("Hey");
    s = reduceThreadEvent(s, { event: "run.event", thread_id: "t", data: { id: "e1", run_id: "r1", seq: 0, type: "tool_call", payload: { name: "x" }, created_at: "" } });
    s = reduceThreadEvent(s, { event: "run.event", thread_id: "t", data: { id: "e1", run_id: "r1", seq: 0, type: "tool_call", payload: { name: "x" }, created_at: "" } });
    expect(s.runEvents["r1"]).toHaveLength(1);
    s = reduceThreadEvent(s, { event: "run.updated", thread_id: "t", data: run("r1", "completed") });
    expect(s.runs["r1"].status).toBe("completed");
    expect(s.streaming["r1"]).toBeUndefined();
  });
});
