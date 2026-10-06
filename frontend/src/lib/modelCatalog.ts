import type { CatalogModel, ProviderInfo } from "../api/types";

export const CATALOG_PROVIDERS = new Set(["openai", "anthropic", "openrouter", "ollama"]);
export const hasCatalog = (provider: string): boolean => CATALOG_PROVIDERS.has(provider);
export interface ModelFilters { text: string; reasoning: boolean; vision: boolean }
export type ModelSort = "newest" | "cheapest";
export interface ModelGroup { label: string; models: CatalogModel[] }

export function placeholderModel(id: string): CatalogModel {
  return { id, name: id, family: "", description: "", reasoning: false, effort_levels: [], image_input: false, context: null, output: null, cost_input: null, cost_output: null, cost_cache_read: null, cost_cache_write: null, cost_tiers: [], release_date: "", status: null };
}
export function withSuggested(models: CatalogModel[], suggested: string[]): CatalogModel[] {
  const known = new Set(models.map((m) => m.id));
  return [...models, ...suggested.filter((id) => !known.has(id)).map(placeholderModel)];
}
export function filterModels(models: CatalogModel[], f: ModelFilters): CatalogModel[] {
  const q = f.text.trim().toLowerCase();
  return models.filter((m) => (!q || m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q) || m.family.toLowerCase().includes(q)) && (!f.reasoning || m.reasoning) && (!f.vision || m.image_input));
}
const byNewest = (a: CatalogModel, b: CatalogModel) => b.release_date.localeCompare(a.release_date) || a.id.localeCompare(b.id);
const byCheapest = (a: CatalogModel, b: CatalogModel) => {
  const ca = a.cost_output ?? Number.POSITIVE_INFINITY, cb = b.cost_output ?? Number.POSITIVE_INFINITY;
  return ca === cb ? byNewest(a, b) : ca - cb;
};
export function sortModels(models: CatalogModel[], sort: ModelSort): CatalogModel[] { return [...models].sort(sort === "cheapest" ? byCheapest : byNewest); }

const TASK_PATTERNS: Array<[string, RegExp]> = [
  ["Reasoning", /reason|think|o[13](?:[-.]|$)|r1|deepseek-r1/],
  ["Vision", /vision|vl|visual|gemini|qwen-vl/],
  ["Code", /code|coder|coding|devstral|starcoder/],
  ["Embeddings", /embed/],
];

export function modelTasks(m: CatalogModel): string[] {
  const text = `${m.id} ${m.name} ${m.description} ${m.family}`.toLowerCase();
  const tasks = TASK_PATTERNS.flatMap(([task, pattern]) => (m.task_ranks?.[task] != null) || (m.reasoning && task === "Reasoning") || (m.image_input && task === "Vision") || pattern.test(text) ? [task] : []);
  return tasks.length ? tasks : ["General"];
}

export function taskRank(task: string, m: CatalogModel): number {
  return m.task_ranks?.[task] ?? Number.POSITIVE_INFINITY;
}

function sortForTask(models: CatalogModel[], task: string, sort: ModelSort): CatalogModel[] {
  return [...models].sort((a, b) => taskRank(task, a) - taskRank(task, b) || (sort === "cheapest" ? byCheapest(a, b) : byNewest(a, b)));
}

/** Filter OpenRouter's catalog to upstreams enabled in this installation. */
export function filterConfiguredProviders(models: CatalogModel[], providers: ProviderInfo[] | undefined): CatalogModel[] {
  if (!providers?.length) return models;
  const configured = new Set(providers.filter((p) => p.configured).map((p) => p.id));
  if (configured.size === 1 && configured.has("openrouter")) return models;
  return models.filter((m) => { const slash = m.id.indexOf("/"); return slash < 0 || configured.has(m.id.slice(0, slash)); });
}

export function groupModels(models: CatalogModel[], suggested: string[], suggestedLabel: string, sort: ModelSort, taskMode = false): ModelGroup[] {
  if (taskMode) {
    const groups = new Map<string, CatalogModel[]>();
    for (const m of models) for (const task of modelTasks(m)) groups.set(task, [...(groups.get(task) ?? []), m]);
    return [...groups].map(([label, ms]) => ({ label, models: sortForTask(ms, label, sort) }));
  }
  const sorted = sortModels(models, sort);
  const byId = new Map(sorted.map((m) => [m.id, m]));
  const pinned = suggested.flatMap((id) => { const m = byId.get(id); return m ? [m] : []; });
  const pinnedIds = new Set(pinned.map((m) => m.id));
  const groups: ModelGroup[] = pinned.length ? [{ label: suggestedLabel, models: pinned }] : [];
  const families = new Map<string, CatalogModel[]>();
  for (const m of sorted) if (!pinnedIds.has(m.id)) { const label = m.family || "Other"; families.set(label, [...(families.get(label) ?? []), m]); }
  for (const [label, ms] of families) groups.push({ label, models: ms });
  return groups;
}
const money = (n: number): string => n > 0 && n < 0.01 ? Number(n.toPrecision(1)).toString() : Number(n.toFixed(2)).toString();
export function formatCost(m: Pick<CatalogModel, "cost_input" | "cost_output">): string { if (m.cost_input == null && m.cost_output == null) return ""; if (m.cost_input === 0 && m.cost_output === 0) return "free"; const part = (v: number | null) => v == null ? "$?" : `$${money(v)}`; return `${part(m.cost_input)} / ${part(m.cost_output)} per M tokens`; }
export function formatContext(n: number | null): string { if (n == null) return ""; if (n >= 1_000_000) return `${Number((n / 1_000_000).toPrecision(2))}M`; return `${Math.round(n / 1000)}k`; }
export function effortLevelsFor(models: CatalogModel[] | undefined, modelId: string): string[] { return models?.find((m) => m.id === modelId)?.effort_levels ?? []; }
export function reconcileEffort(settings: Record<string, unknown>, models: CatalogModel[] | undefined, modelId: string): Record<string, unknown> { const effort = settings.reasoning_effort; const m = models?.find((x) => x.id === modelId); if (typeof effort !== "string" || !m || m.effort_levels.includes(effort)) return settings; const { reasoning_effort: _, ...rest } = settings; return rest; }
export function splitAutoDefault(autoDefaultModel: string | undefined): { provider: string; model: string } | null { if (!autoDefaultModel) return null; const i = autoDefaultModel.indexOf("/"); return i < 0 ? null : { provider: autoDefaultModel.slice(0, i), model: autoDefaultModel.slice(i + 1) }; }
