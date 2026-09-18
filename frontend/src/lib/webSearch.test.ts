import { describe, expect, it } from "vitest";
import { supportsWebSearch } from "./webSearch";

describe("supportsWebSearch", () => {
  it("is offered for providers with a hosted search tool", () => {
    expect(supportsWebSearch("openai")).toBe(true);
    expect(supportsWebSearch("anthropic")).toBe(true);
    expect(supportsWebSearch("openrouter")).toBe(true);
    expect(supportsWebSearch("xai")).toBe(false);
    expect(supportsWebSearch("ollama")).toBe(false);
  });

  it("follows the resolved provider for auto bots", () => {
    // The providers endpoint reports auto's default_model as "<provider>/<model>".
    expect(supportsWebSearch("auto", "openrouter/openai/gpt-5.5")).toBe(true);
    expect(supportsWebSearch("auto", "anthropic/claude-sonnet-5")).toBe(true);
    expect(supportsWebSearch("auto", "xai/grok-4.6")).toBe(false);
    expect(supportsWebSearch("auto", "")).toBe(false);
    expect(supportsWebSearch("auto", undefined)).toBe(false);
  });
});
