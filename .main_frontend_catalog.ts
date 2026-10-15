import type { CatalogModel } from "../api/types";

/** Providers the backend serves a models.dev catalog for (GET /models). xAI keeps its builtin list. */
export const CATALOG_PROVIDERS = new Set(["openai", "anthropic", "openrouter", "ollama"]);
export const hasCatalog = (provider: string): boolean => CATALOG_PROVIDERS.has(provider);

export interface ModelFilters { text: string; reasoning: boolean; vision: boolean }
export type ModelSort = "newest" | "cheapest";
export interface ModelGroup { label: string; models: CatalogModel[] }

/** A bare row for an id the catalog does not know: an installed Ollama tag, or the configured default. */
export function placeholderModel(id: string): CatalogModel {
  return { id, name: id, family: "", description: "", reasoning: false, effort_levels: [], image_input: false, context: null, output: null, cost_input: null, cost_output: null, cost_cache_read: null, cost_cache_write: null, cost_tiers: [], release_date: "", status: null };
}

/** The catalog plus a placeholder for every suggested id it does not know, so those still list and pin. */
export function withSuggested(models: CatalogModel[], suggested: string[]): CatalogModel[] {
  const known = new Set(models.map((m) => m.id));
  return [...models, ...suggested.filter((id) => !known.has(id)).map(placeholderModel)];
}

/** Case-insensitive substring match on id, name and family; the chips narrow further. */
export function filterModels(models: CatalogModel[], f: ModelFilters): CatalogModel[] {
  const q = f.text.trim().toLowerCase();
  return models.filter((m) =>
    (!q || m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q) || m.family.toLowerCase().includes(q))
    && (!f.reasoning || m.reasoning) && (!f.vision || m.image_input));
}

const byNewest = (a: CatalogModel, b: CatalogModel) => b.release_date.localeCompare(a.release_date) || a.id.localeCompare(b.id);
const byCheapest = (a: CatalogModel, b: CatalogModel) => {
  const ca = a.cost_output ?? Number.POSITIVE_INFINITY, cb = b.cost_output ?? Number.POSITIVE_INFINITY;
  if (ca === cb) return byNewest(a, b);
  return ca - cb;
};
export function sortModels(models: CatalogModel[], sort: ModelSort): CatalogModel[] {
  return [...models].sort(sort === "cheapest" ? byCheapest : byNewest);
}

/** Pinned group first (suggested ids in their given order, only those present in `models`), then one
 *  group per family, families in the order their best-ranked model appears under `sort`. */
export function groupModels(models: CatalogModel[], suggested: string[], suggestedLabel: string, sort: ModelSort): ModelGroup[] {
  const sorted = sortModels(models, sort);
  const byId = new Map(sorted.map((m) => [m.id, m]));
  const pinned = suggested.flatMap((id) => { const m = byId.get(id); return m ? [m] : []; });
  const pinnedIds = new Set(pinned.map((m) => m.id));
  const groups: ModelGroup[] = pinned.length ? [{ label: suggestedLabel, models: pinned }] : [];
  const families = new Map<string, CatalogModel[]>();
  for (const m of sorted) {
    if (pinnedIds.has(m.id)) continue;
    const label = m.family || "Other";
    const g = families.get(label);
    if (g) g.push(m); else families.set(label, [m]);
  }
  for (const [label, ms] of families) groups.push({ label, models: ms });
  return groups;
}

/** Up to two decimals, trailing zeros dropped; sub-cent prices keep one significant digit ($0.003). */
const money = (n: number): string => (n > 0 && n < 0.01 ? Number(n.toPrecision(1)).toString() : Number(n.toFixed(2)).toString());

/** "$1.25 / $10 per M tokens" (input / output); "free" when both are zero; "" when both are unknown. */
export function formatCost(m: Pick<CatalogModel, "cost_input" | "cost_output">): string {
  if (m.cost_input == null && m.cost_output == null) return "";
  if (m.cost_input === 0 && m.cost_output === 0) return "free";
  const part = (v: number | null) => (v == null ? "$?" : `$${money(v)}`);
  return `${part(m.cost_input)} / ${part(m.cost_output)} per M tokens`;
}

/** 200000 -> "200k", 1048576 -> "1M". */
export function formatContext(n: number | null): string {
  if (n == null) return "";
  if (n >= 1_000_000) return `${Number((n / 1_000_000).toPrecision(2))}M`;
  return `${Math.round(n / 1000)}k`;
}

/** Effort levels the catalog declares for `modelId`; [] when unknown or not effort-capable. */
export function effortLevelsFor(models: CatalogModel[] | undefined, modelId: string): string[] {
  return models?.find((m) => m.id === modelId)?.effort_levels ?? [];
}

/** model_settings without a reasoning_effort the catalog says this model does not accept. A model the
 *  catalog does not know (typed by hand, or a catalog that has not loaded) keeps whatever is set: the
 *  provider is the authority there. */
export function reconcileEffort(settings: Record<string, unknown>, models: CatalogModel[] | undefined, modelId: string): Record<string, unknown> {
  const effort = settings.reasoning_effort;
  const m = models?.find((x) => x.id === modelId);
  if (typeof effort !== "string" || !m || m.effort_levels.includes(effort)) return settings;
  const { reasoning_effort: _, ...rest } = settings;
  return rest;
}

/** The provider and model an "auto" bot resolves to, from /providers' `default_model` ("<provider>/<model>"). */
export function splitAutoDefault(autoDefaultModel: string | undefined): { provider: string; model: string } | null {
  if (!autoDefaultModel) return null;
  const i = autoDefaultModel.indexOf("/");
  return i < 0 ? null : { provider: autoDefaultModel.slice(0, i), model: autoDefaultModel.slice(i + 1) };
}
