const MENTION = /(?<![\w@.])@([a-z0-9_-]{2,32})(?![\w-])(?!\.\w)/g;

export function parseMentions(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(MENTION)) if (!out.includes(m[1])) out.push(m[1]);
  return out;
}

export function mentionQuery(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const m = /(?:^|[\s(])@([a-z0-9_-]*)$/.exec(before);
  if (!m) return null;
  return { start: caret - m[1].length - 1, query: m[1] };
}

export function applyMention(text: string, start: number, caret: number, handle: string): { text: string; caret: number } {
  const inserted = `@${handle} `;
  const next = text.slice(0, start) + inserted + text.slice(caret);
  return { text: next, caret: start + inserted.length };
}
