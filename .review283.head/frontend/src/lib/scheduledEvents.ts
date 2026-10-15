import type { BusEvent } from "../api/types";

/** Invalidate the scheduled queue whenever the backend reports a schedule transition. */
export function refreshScheduledMessages(event: Pick<BusEvent, "event">, invalidate: () => void): void {
  if (event.event === "scheduled.updated") invalidate();
}

/** Re-fetch the queue after SSE reconnect because missed events are not replayed. */
export function refreshScheduledQueue(invalidate: () => void): void {
  invalidate();
}
