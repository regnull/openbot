import type { Thread } from "../api/types";
import { parseTs } from "./time";

/** How many minutes of recency make a thread "active" for the sidebar dot. */
export const ACTIVE_THREAD_WINDOW_MS = 5 * 60 * 1000;

/** A thread is considered active when its most recent message is within the activity window. */
export function isThreadActive(t: Thread, now = Date.now()): boolean {
  const ref = t.last_message_at ?? t.updated_at;
  return now - parseTs(ref).getTime() < ACTIVE_THREAD_WINDOW_MS;
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
