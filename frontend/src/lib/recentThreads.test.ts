import { describe, expect, it } from "vitest";
import type { Thread } from "../api/types";
import { isThreadActive, RECENT_THREADS_LIMIT, recentThreads, threadLabel } from "./recentThreads";

const thread = (id: string, last: string | null, updated = "2026-01-01T00:00:00Z", title = ""): Thread => ({
  id, title, kind: "chat", created_by_actor_id: null, default_bot_actor_id: null, default_bot_handle: null, working_directory: null,
  external_ref: null, created_at: updated, updated_at: updated, last_message_at: last,
  active: false,
  participants: [{ actor_id: "a", kind: "human", handle: "you", name: "You" }, { actor_id: "b", kind: "bot", handle: "eng", name: "Engineer" }],
});

describe("recentThreads", () => {
  it("returns at most the limit, most recently active first, and says whether more exist", () => {
    const threads = [
      thread("old", "2026-01-01T00:00:00Z"),
      thread("new", "2026-01-06T00:00:00Z"),
      thread("mid", "2026-01-03T00:00:00Z"),
      thread("nomsg", null, "2026-01-05T00:00:00Z"),
      thread("t5", "2026-01-02T00:00:00Z"),
      thread("t6", "2026-01-04T00:00:00Z"),
    ];
    const { visible, hasMore } = recentThreads(threads);
    expect(RECENT_THREADS_LIMIT).toBe(5);
    expect(visible.map((t) => t.id)).toEqual(["new", "nomsg", "t6", "mid", "t5"]);
    expect(hasMore).toBe(true);
  });

  it("reports no more when the list fits", () => {
    const { visible, hasMore } = recentThreads([thread("a", null), thread("b", null)]);
    expect(visible).toHaveLength(2);
    expect(hasMore).toBe(false);
  });

  it("handles undefined input", () => {
    expect(recentThreads(undefined)).toEqual({ visible: [], hasMore: false });
  });
});

describe("threadLabel", () => {
  it("uses the title when present, otherwise the participant handles", () => {
    expect(threadLabel(thread("a", null, "2026-01-01T00:00:00Z", "Ship it"))).toBe("Ship it");
    expect(threadLabel(thread("a", null))).toBe("you, eng");
  });
});

describe("isThreadActive", () => {
  it("returns true when the server reports a live active run", () => {
    const now = new Date("2026-06-01T12:00:00Z").getTime();
    const twoMinutesAgo = new Date(now - 2 * 60 * 1000).toISOString();
    expect(isThreadActive({ ...thread("a", twoMinutesAgo), active: true }, now)).toBe(true);
  });

  it("returns false when the server reports no live active run, even for a recent message", () => {
    const now = new Date("2026-06-01T12:00:00Z").getTime();
    expect(isThreadActive({ ...thread("a", new Date(now - 1_000).toISOString()), active: false }, now)).toBe(false);
  });

  it("returns false when active is false at the activity window boundary", () => {
    const now = new Date("2026-06-01T12:00:00Z").getTime();
    const atBoundary = new Date(now - 5 * 60 * 1000).toISOString();
    expect(isThreadActive({ ...thread("a", atBoundary), active: false }, now)).toBe(false);
  });

  it("returns true for an active thread even when its message is old", () => {
    const now = new Date("2026-06-01T12:00:00Z").getTime();
    const oneMinuteAgo = new Date(now - 1 * 60 * 1000).toISOString();
    expect(isThreadActive({ ...thread("a", null, oneMinuteAgo), active: true }, now)).toBe(true);
  });

  it("returns false for an inactive thread even when its updated_at is recent", () => {
    const now = new Date("2026-06-01T12:00:00Z").getTime();
    const oneSecondAgo = new Date(now - 1_000).toISOString();
    expect(isThreadActive({ ...thread("a", null, oneSecondAgo), active: false }, now)).toBe(false);
  });
});
