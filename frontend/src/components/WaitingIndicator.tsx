import type { Waiter } from "../api/types";

/**
 * The "@eng — waiting to pick up this thread" line under the thread header.
 *
 * `waiters` is the set of bots with queued, unpicked mail in this thread, published by the backend as
 * `waiters.updated` and seeded from GET /threads/{id}. A bot that is running this very thread has
 * already been picked up (its items are "processing"), so it never appears here — the run card below
 * covers that state.
 */
export default function WaitingIndicator({ waiters }: { waiters?: Waiter[] }) {
  const list = waiters ?? [];
  if (list.length === 0) return null;
  return (
    <div className="space-y-0.5 py-1" aria-live="polite">
      {list.map((w) => {
        const label = w.name || w.handle || w.actor_id;
        const at = w.handle ? `@${w.handle}` : label;
        const behind = w.queue_len > w.position ? ` (behind ${w.queue_len - w.position} item${w.queue_len - w.position === 1 ? "" : "s"})` : "";
        return (
          <div key={w.actor_id} className="flex items-center gap-2 text-xs text-warn" title={`This bot has queued, unpicked mail in this thread: position ${w.position} of ${w.queue_len} in its queue`}>
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn" aria-hidden />
            <span>{at} — waiting to pick up this thread{behind}</span>
          </div>
        );
      })}
    </div>
  );
}
