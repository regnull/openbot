import { describe, expect, it } from "vitest";
import type { CatalogModel } from "../api/types";
import { effortLevelsFor, filterModels, filterConfiguredProviders, formatContext, formatCost, groupModels, hasCatalog, reconcileEffort, sortModels, splitAutoDefault, taskRank, withSuggested } from "./modelCatalog";

const model = (id: string, extra: Partial<CatalogModel> = {}): CatalogModel => ({
  id, name: id, family: "", description: "", reasoning: false, effort_levels: [], image_input: false, context: 200000, output: null,
  cost_input: 1, cost_output: 5, release_date: "2026-01-01", status: null, ...extra,
});
const opus = model("claude-opus-5-5", { name: "Claude Opus 5.5", family: "claude-opus", reasoning: true, effort_levels: ["low", "high"], image_input: true, cost_input: 5, cost_output: 25, release_date: "2026-03-01" });
const sonnet = model("claude-sonnet-4-5", { name: "Claude Sonnet 4.5", family: "claude-sonnet", reasoning: true, cost_input: 3, cost_output: 15, release_date: "2025-09-29" });
const haiku = model("claude-haiku-4-5", { name: "Claude Haiku 4.5", family: "claude-haiku", release_date: "2025-10-15" });
const older = model("claude-opus-4-5", { name: "Claude Opus 4.5", family: "claude-opus", reasoning: true, release_date: "2025-11-01" });
const all = [haiku, opus, sonnet, older];

describe("filterModels", () => {
  it("matches id, name and family case-insensitively and applies chips", () => {
    const ids = (ms: CatalogModel[]) => ms.map((m) => m.id);
    expect(ids(filterModels(all, { text: "", reasoning: false, vision: false }))).toEqual(ids(all));
    expect(ids(filterModels(all, { text: "Claude-Opus-5", reasoning: false, vision: false }))).toEqual(["claude-opus-5-5"]);
    expect(ids(filterModels(all, { text: "sonnet 4", reasoning: false, vision: false }))).toEqual(["claude-sonnet-4-5"]);
    expect(ids(filterModels(all, { text: "HAIKU", reasoning: false, vision: false }))).toEqual(["claude-haiku-4-5"]);
    expect(ids(filterModels(all, { text: "", reasoning: true, vision: false }))).toEqual(["claude-opus-5-5", "claude-sonnet-4-5", "claude-opus-4-5"]);
    expect(ids(filterModels(all, { text: "", reasoning: true, vision: true }))).toEqual(["claude-opus-5-5"]);
  });
});

describe("sortModels and groupModels", () => {
  it("orders newest first by default and cheapest first on request, unknown cost last", () => {
    expect(sortModels(all, "newest").map((m) => m.id)).toEqual(["claude-opus-5-5", "claude-opus-4-5", "claude-haiku-4-5", "claude-sonnet-4-5"]);
    const free = model("free", { cost_input: 0, cost_output: 0 });
    const unknown = model("unknown", { cost_input: null, cost_output: null });
    expect(sortModels([opus, unknown, haiku, free], "cheapest").map((m) => m.id)).toEqual(["free", "claude-haiku-4-5", "claude-opus-5-5", "unknown"]);
  });
  it("groups by family in rank order with the suggested group pinned first and not repeated", () => {
    const groups = groupModels(all, ["claude-haiku-4-5"], "Suggested", "newest");
    expect(groups.map((g) => [g.label, g.models.map((m) => m.id)])).toEqual([
      ["Suggested", ["claude-haiku-4-5"]],
      ["claude-opus", ["claude-opus-5-5", "claude-opus-4-5"]],
      ["claude-sonnet", ["claude-sonnet-4-5"]],
    ]);
    expect(groupModels(all, [], "Suggested", "newest")[0].label).toBe("claude-opus");
    expect(groupModels([model("x")], [], "Suggested", "newest")[0].label).toBe("Other");
  });
  it("keeps an installed model the catalog does not know, with a bare name", () => {
    const merged = withSuggested([opus], ["qwen3:8b", "claude-opus-5-5"]);
    expect(merged.map((m) => m.id)).toEqual(["claude-opus-5-5", "qwen3:8b"]);
    const groups = groupModels(merged, ["qwen3:8b", "claude-opus-5-5"], "Installed", "newest");
    expect(groups[0].label).toBe("Installed");
    expect(groups[0].models.map((m) => [m.id, m.name, m.context])).toEqual([["qwen3:8b", "qwen3:8b", null], ["claude-opus-5-5", "Claude Opus 5.5", 200000]]);
    expect(groups).toHaveLength(1);
  });
  it("ranks task groups by the task leaderboard, then uses the selected sort as a fallback", () => {
    const ranked = model("deepseek/deepseek-v4.1-flash", { description: "coding", release_date: "2025-01-01", task_ranks: { Code: 1 } });
    const second = model("z-ai/glm-5.3-flash", { description: "coding", release_date: "2026-01-01", task_ranks: { Code: 2 } });
    const fallback = model("unknown/coder", { description: "coding", release_date: "2026-02-01" });
    const arbitrary = model("new/provider-model", { name: "Provider Model", description: "general purpose", task_ranks: { Code: 3 } });
    expect(taskRank("Code", ranked)).toBeLessThan(taskRank("Code", second));
    expect(groupModels([fallback, second, ranked, arbitrary], [], "Suggested", "newest", true)[0].models.map((m) => m.id)).toEqual([ranked.id, second.id, arbitrary.id, fallback.id]);
  });
});

describe("OpenRouter provider filtering", () => {
  it("keeps only models from configured upstreams and unqualified models", () => {
    const models = [model("anthropic/claude"), model("openai/gpt"), model("custom/model"), model("bare")];
    const providers = [{ id: "anthropic", configured: true }, { id: "openai", configured: false }] as never;
    expect(filterConfiguredProviders(models, providers).map((m) => m.id)).toEqual(["anthropic/claude", "bare"]);
  });
});

describe("formatting", () => {
  it("formats cost per million tokens", () => {
    expect(formatCost({ cost_input: 1.25, cost_output: 10 })).toBe("$1.25 / $10 per M tokens");
    expect(formatCost({ cost_input: 0.003, cost_output: 0.5 })).toBe("$0.003 / $0.5 per M tokens");
    expect(formatCost({ cost_input: 0, cost_output: 0 })).toBe("free");
    expect(formatCost({ cost_input: null, cost_output: null })).toBe("");
    expect(formatCost({ cost_input: null, cost_output: 2 })).toBe("$? / $2 per M tokens");
    expect(formatCost({ cost_input: 0, cost_output: null })).toBe("$0 / $? per M tokens");
  });
  it("formats context windows", () => {
    expect(formatContext(200000)).toBe("200k");
    expect(formatContext(131072)).toBe("131k");
    expect(formatContext(1048576)).toBe("1M");
    expect(formatContext(null)).toBe("");
  });
});

describe("effort helpers", () => {
  it("reads effort levels of a known model and nothing for unknown ones", () => {
    expect(effortLevelsFor(all, "claude-opus-5-5")).toEqual(["low", "high"]);
    expect(effortLevelsFor(all, "claude-haiku-4-5")).toEqual([]);
    expect(effortLevelsFor(all, "typed-by-hand")).toEqual([]);
    expect(effortLevelsFor(undefined, "claude-opus-5-5")).toEqual([]);
  });
  it("drops an effort the catalog says the model does not accept, keeps it for unknown models", () => {
    expect(reconcileEffort({ reasoning_effort: "high", web_search: true }, all, "claude-opus-5-5")).toEqual({ reasoning_effort: "high", web_search: true });
    expect(reconcileEffort({ reasoning_effort: "max", web_search: true }, all, "claude-opus-5-5")).toEqual({ web_search: true });
    expect(reconcileEffort({ reasoning_effort: "high" }, all, "claude-haiku-4-5")).toEqual({});
    expect(reconcileEffort({ reasoning_effort: "high" }, all, "typed-by-hand")).toEqual({ reasoning_effort: "high" });
    expect(reconcileEffort({ reasoning_effort: "high" }, undefined, "claude-haiku-4-5")).toEqual({ reasoning_effort: "high" });
  });
  it("splits the auto provider's resolved default and knows which providers have a catalog", () => {
    expect(splitAutoDefault("openrouter/anthropic/claude-sonnet-5")).toEqual({ provider: "openrouter", model: "anthropic/claude-sonnet-5" });
    expect(splitAutoDefault("")).toBeNull();
    expect(splitAutoDefault(undefined)).toBeNull();
    expect(hasCatalog("ollama")).toBe(true);
    expect(hasCatalog("xai")).toBe(false);
  });
});
