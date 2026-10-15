const drafts = new Map<string, string>();
// Bumped on every edit, so a send can tell "still what I sent" from "typed since", even when the text is the same.
const revisions = new Map<string, number>();
// Revision a send still in flight started from, per thread. Its text stays in `drafts` until the send
// succeeds (a failed send keeps it), but a composer mounted meanwhile must not offer it as unsent.
const sending = new Map<string, number>();
const failureListeners = new Map<string, Set<(text: string) => void>>();

const revision = (threadId: string): number => revisions.get(threadId) ?? 0;

export function getThreadDraft(threadId: string): string {
  return sending.get(threadId) === revision(threadId) ? "" : drafts.get(threadId) ?? "";
}

export function setThreadDraft(threadId: string, text: string): void {
  revisions.set(threadId, revision(threadId) + 1);
  if (text) drafts.set(threadId, text);
  else drafts.delete(threadId);
}

export function clearThreadDraft(threadId: string): void {
  drafts.delete(threadId);
  sending.delete(threadId);
}

export function beginThreadSend(threadId: string): number {
  const rev = revision(threadId);
  sending.set(threadId, rev);
  return rev;
}

/** Settles a send. Returns whether the draft is still the one that was sent, i.e. nothing was typed since. */
export function endThreadSend(threadId: string, rev: number, ok: boolean): boolean {
  if (sending.get(threadId) === rev) sending.delete(threadId);
  if (revision(threadId) !== rev) return false;
  if (ok) drafts.delete(threadId);
  else failureListeners.get(threadId)?.forEach((listener) => listener(drafts.get(threadId) ?? ""));
  return true;
}

/** Hands the unsent text to a composer that was mounted after the send started, when that send fails. */
export function onThreadSendFailed(threadId: string, listener: (text: string) => void): () => void {
  const listeners = failureListeners.get(threadId) ?? new Set();
  failureListeners.set(threadId, listeners.add(listener));
  return () => { listeners.delete(listener); };
}
