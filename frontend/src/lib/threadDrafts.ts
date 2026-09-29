const drafts = new Map<string, string>();

export function getThreadDraft(threadId: string): string {
  return drafts.get(threadId) ?? "";
}

export function setThreadDraft(threadId: string, text: string): void {
  if (text) drafts.set(threadId, text);
  else drafts.delete(threadId);
}

export function clearThreadDraft(threadId: string): void {
  drafts.delete(threadId);
}
