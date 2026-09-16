import { describe, expect, it } from "vitest";
import { usageLabel } from "../components/RunCard";

describe("usageLabel", () => {
  it("is null until the run has reported any model call", () => {
    expect(usageLabel({ prompt_tokens: null, completion_tokens: null, cache_read_tokens: null, model_calls: null })).toBeNull();
  });

  it("shows compact totals, the cached share of the prompt, and the call count", () => {
    expect(usageLabel({ prompt_tokens: 12000, completion_tokens: 300, cache_read_tokens: 9600, model_calls: 7 })).toBe("12.3k tok (80% cached) · 7 model calls");
    expect(usageLabel({ prompt_tokens: 800, completion_tokens: 20, cache_read_tokens: 0, model_calls: 1 })).toBe("820 tok · 1 model call");
    expect(usageLabel({ prompt_tokens: 2_500_000, completion_tokens: 0, cache_read_tokens: null, model_calls: 90 })).toBe("2.5M tok · 90 model calls");
  });
});
