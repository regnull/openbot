import { describe, expect, it, vi } from "vitest";
import { refreshScheduledMessages } from "./scheduledEvents";

describe("refreshScheduledMessages", () => {
  it("invalidates the scheduled queue for SSE updates", () => {
    const invalidate = vi.fn();
    refreshScheduledMessages({ event: "scheduled.updated" }, invalidate);
    expect(invalidate).toHaveBeenCalledOnce();
  });

  it("preserves unrelated SSE behavior", () => {
    const invalidate = vi.fn();
    refreshScheduledMessages({ event: "message.created" }, invalidate);
    expect(invalidate).not.toHaveBeenCalled();
  });
});
