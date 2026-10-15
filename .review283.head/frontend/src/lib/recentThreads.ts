import type { Thread } from "../api/types";

/** A thread is considered active when its most recent message is within the activity window. */
export function isThreadActive(t: Thread, _now = Date.now()): boolean {
  // Server-derived live-run state; recent messages remain after completion.
  return t.active === true;
}

/** How many threads the sidebar shows before offering "See more". */
export const RECENT_THREADS_LIMIT = 5;

const activity = (t: Thread) => t.last_message_at ?? t.updated_at;

/** The most recently active threads, capped for the sidebar, plus whether the full list has more. */
export function recentThreads(threads: Thread[] | undefined, limit = RECENT_THREADS_LIMIT): { visible: Thread[]; hasMore: boolean } {
  if (!threads) return { visible: [], hasMore: false };
  const sorted = [...threads].sort((a, b) => activity(b).localeCompare(activity(a)));
  return { visible: sorted.slice(0, limit), hasMore: sorted.length > limit };
}

/** Display name for a thread: its title, or the participant handles when it has none. */
export function threadLabel(t: Thread): string {
  return t.title || t.participants.map((p) => p.handle).join(", ");
}
