import type { ThreadUsage } from "../api/types";

export const compact = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

/** Header line with the thread's running LLM totals; null until any run has made a model call. */
export function threadUsageLabel(u: ThreadUsage): string | null {
  if (!u.model_calls) return null;
  return `${u.model_calls} LLM call${u.model_calls === 1 ? "" : "s"} · ${compact(u.prompt_tokens)} in · ${compact(u.completion_tokens)} out`;
}
