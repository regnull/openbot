import { describe, expect, it } from "vitest";
import { threadUsageLabel } from "./threadUsage";

describe("threadUsageLabel", () => {
  it("is null until any run in the thread has made a model call", () => {
    expect(threadUsageLabel({ model_calls: 0, prompt_tokens: 0, completion_tokens: 0, cache_read_tokens: 0 })).toBeNull();
  });

  it("shows the call count and compact input/output token totals", () => {
    expect(threadUsageLabel({ model_calls: 7, prompt_tokens: 34_500, completion_tokens: 2_100, cache_read_tokens: 0 })).toBe("7 LLM calls · 34.5k in · 2.1k out");
    expect(threadUsageLabel({ model_calls: 1, prompt_tokens: 820, completion_tokens: 40, cache_read_tokens: 0 })).toBe("1 LLM call · 820 in · 40 out");
    expect(threadUsageLabel({ model_calls: 90, prompt_tokens: 2_500_000, completion_tokens: 12_000, cache_read_tokens: 9 })).toBe("90 LLM calls · 2.5M in · 12.0k out");
  });
});
