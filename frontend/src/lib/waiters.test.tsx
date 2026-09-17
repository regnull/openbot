// @vitest-environment jsdom
// React 19: act() must know it runs in a test environment (no RTL here to set it for us).
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { describe, expect, it } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import WaitingIndicator from "../components/WaitingIndicator";
import { emptyThreadState, hydrate, reduceThreadEvent } from "./threadState";
import type { Waiter } from "../api/types";

// The waiter payload the backend broadcasts / serves (see WaiterOut in api/schemas.py).
const waiter = (over: Partial<Waiter> = {}): Waiter =>
  ({ actor_id: "a1", handle: "eng", name: "Engineer", position: 1, count: 1, queue_len: 1, ...over });

describe("waiters in threadState", () => {
  it("shows the waiting state from a waiters.updated event and clears it", () => {
    let s = emptyThreadState("t");
    s = reduceThreadEvent(s, { event: "waiters.updated", thread_id: "t", data: { waiters: [waiter()] } });
    expect(s.waiters).toHaveLength(1);
    expect(s.waiters[0].handle).toBe("eng");
    // The bot picked the items up: the backend publishes an empty list, the banner disappears.
    s = reduceThreadEvent(s, { event: "waiters.updated", thread_id: "t", data: { waiters: [] } });
    expect(s.waiters).toHaveLength(0);
  });
  it("seeds waiters from the thread detail and tolerates a missing field", () => {
    let s = emptyThreadState("t");
    s = hydrate(s, { messages: [], runs: [], waiters: [waiter()] } as any);
    expect(s.waiters).toHaveLength(1);
    // A page rendered against an older backend: no waiters field, degrades to none.
    s = hydrate(s, { messages: [], runs: [] } as any);
    expect(s.waiters).toHaveLength(0);
  });
  it("ignores waiters events from other threads via the SSE filter", () => {
    let s = emptyThreadState("t");
    s = reduceThreadEvent(s, { event: "waiters.updated", thread_id: "other", data: { waiters: [waiter()] } });
    expect(s.waiters).toHaveLength(0);
  });
});

describe("WaitingIndicator", () => {
  it("renders one line per waiting bot and nothing when nobody waits", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    try {
      act(() => root.render(<WaitingIndicator waiters={[waiter(), waiter({ actor_id: "a2", handle: "rev", name: "Reviewer", position: 2, queue_len: 3 })]} />));
      const lines = container.querySelectorAll("div.flex > span:last-child");
      expect(container.textContent).toContain("@eng — waiting to pick up this thread");
      expect(container.textContent).toContain("@rev — waiting to pick up this thread (behind 1 item)");
      expect(lines).toHaveLength(2);
      const live = container.querySelector("div[aria-live]");
      expect(live?.getAttribute("aria-live")).toBe("polite");
      act(() => root.render(<WaitingIndicator waiters={[]} />));
      expect(container.textContent).toBe("");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });
});
