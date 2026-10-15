import type { Run } from "../api/types";
import { compact } from "./threadUsage";

/** "12.3k tok (78% cached)" — prompt + completion tokens over the run, with the cached share of the prompt. */
export function usageLabel(run: Pick<Run, "prompt_tokens" | "completion_tokens" | "cache_read_tokens" | "model_calls">): string | null {
  if (run.model_calls == null || run.prompt_tokens == null) return null;
  const total = run.prompt_tokens + (run.completion_tokens ?? 0);
  const cached = run.cache_read_tokens && run.prompt_tokens > 0 ? Math.round((run.cache_read_tokens / run.prompt_tokens) * 100) : 0;
  return `${compact(total)} tok${cached > 0 ? ` (${cached}% cached)` : ""} · ${run.model_calls} model call${run.model_calls === 1 ? "" : "s"}`;
}
