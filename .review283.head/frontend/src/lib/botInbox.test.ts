import { describe, expect, it } from "vitest";
import type { BotInboxItem } from "../api/types";
import { hasOpenItems, inboxRowState, purgeSummary } from "./botInbox";

const base: BotInboxItem = {
  id: "i1", actor_id: "b", thread_id: "t", thread_kind: "direct", kind: "message", message_id: "m", run_id: null, payload: {},
  status: "queued", attempts: 0, last_error: null, created_at: "2026-09-16T10:00:00", processed_at: null,
  message: null, run_status: null, reply: null,
};

describe("inboxRowState", () => {
  it("follows the item while it waits and the run while it works", () => {
    expect(inboxRowState(base)).toEqual({ label: "queued", tone: "zinc", open: true });
    expect(inboxRowState({ ...base, status: "processing", run_status: "running" })).toEqual({ label: "running", tone: "blue", open: true });
    expect(inboxRowState({ ...base, status: "processing", run_status: "waiting_human" })).toEqual({ label: "waiting for you", tone: "amber", open: true });
  });
  it("reports how the run ended", () => {
    expect(inboxRowState({ ...base, status: "done", run_status: "completed", reply: { content: "ok" } as never })).toEqual({ label: "replied", tone: "green", open: false });
    expect(inboxRowState({ ...base, status: "done", run_status: "completed" })).toEqual({ label: "done, no reply", tone: "zinc", open: false });
    expect(inboxRowState({ ...base, status: "done", run_status: "failed" })).toEqual({ label: "failed", tone: "red", open: false });
    expect(inboxRowState({ ...base, status: "cancelled", run_status: "cancelled" })).toEqual({ label: "cancelled", tone: "zinc", open: false });
  });
});

describe("hasOpenItems", () => {
  it("is true while any item is still queued or running, which drives polling", () => {
    expect(hasOpenItems([{ ...base, status: "done", run_status: "completed" }])).toBe(false);
    expect(hasOpenItems([{ ...base, status: "done", run_status: "completed" }, base])).toBe(true);
    expect(hasOpenItems([])).toBe(false);
  });
});

describe("purgeSummary", () => {
  it("reads naturally for zero, one and many", () => {
    expect(purgeSummary({ cancelled_runs: 0, purged_items: 0 })).toBe("Nothing to cancel: no open run and an empty queue.");
    expect(purgeSummary({ cancelled_runs: 1, purged_items: 1 })).toBe("Cancelled 1 run, dropped 1 queued item.");
    expect(purgeSummary({ cancelled_runs: 2, purged_items: 3 })).toBe("Cancelled 2 runs, dropped 3 queued items.");
  });
});
