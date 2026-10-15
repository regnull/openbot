// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Api } from "../api/client";
import type { CatalogModel, ModelsOut } from "../api/types";
import { ModelPicker } from "./ModelPicker";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const model = (id: string, extra: Partial<CatalogModel> = {}): CatalogModel => ({
  id, name: id, family: "", description: "", reasoning: false, effort_levels: [], image_input: false, context: 200000, output: null,
  cost_input: 1, cost_output: 5, release_date: "2026-01-01", status: null, ...extra,
});
const catalog: ModelsOut = {
  provider: "anthropic", configured: true, source: "catalog", stale: false, fetched_at: "2026-09-27T00:00:00Z",
  models: [
    model("claude-opus-5-5", { name: "Claude Opus 5.5", family: "Claude", description: "Most capable reasoning model", reasoning: true, effort_levels: ["low", "high"], image_input: true, cost_input: 5, cost_output: 25, release_date: "2026-03-01" }),
    model("claude-haiku-4-5", { name: "Claude Haiku 4.5", family: "Claude", description: "Fast general model", release_date: "2025-10-15" }),
    model("code-model", { name: "Code Model", family: "Code", description: "Code generation", release_date: "2026-02-01" }),
    model("embed-model", { name: "Embed Model", family: "Embeddings", description: "Text embeddings", release_date: "2026-01-15" }),
  ],
};

let root: Root; let el: HTMLDivElement; let qc: QueryClient; let currentValue = "";
function Host({ initial = "", suggested = [] as string[], provider = "anthropic", suggestedLabel = "Suggested" }) {
  const [value, setValue] = useState(initial);
  return <ModelPicker provider={provider} value={value} onChange={(next) => { currentValue = next; setValue(next); }} suggested={suggested} suggestedLabel={suggestedLabel} />;
}
async function show(props: Parameters<typeof Host>[0] = {}) {
  await act(async () => root.render(<QueryClientProvider client={qc}><Host {...props} /></QueryClientProvider>));
  await act(async () => { await Promise.resolve(); });
}
const pickerInput = () => el.querySelector<HTMLInputElement>("input[role=combobox]")!;
const dialog = () => document.body.querySelector<HTMLElement>("[role=dialog]");
const search = () => dialog()!.querySelector<HTMLInputElement>("input[aria-label='Search model IDs, names, or families']")!;
const options = () => [...document.body.querySelectorAll<HTMLElement>("[role=option]")];
const click = (element: Element) => act(async () => { element.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
const key = (element: Element, keyName: string, init: KeyboardEventInit = {}) => act(async () => { element.dispatchEvent(new KeyboardEvent("keydown", { key: keyName, bubbles: true, ...init })); });
const until = async (predicate: () => boolean, message: string) => { for (let i = 0; i < 20; i += 1) { if (predicate()) return; await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); }); } throw new Error(message); };

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(Api, "getModels").mockResolvedValue(catalog);
  vi.spyOn(Api, "getProviders").mockResolvedValue({ providers: [], embedding_model: "", embeddings_configured: false });
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(async () => { await act(async () => root.unmount()); document.body.replaceChildren(); qc.clear(); vi.restoreAllMocks(); });

it("opens a modal browser with consistent dialog/listbox semantics and searchable rows", async () => {
  await show();
  expect(dialog()).toBeNull();
  await click(pickerInput());
  expect(dialog()).not.toBeNull();
  expect(dialog()?.getAttribute("aria-labelledby")).toBeTruthy();
  expect(dialog()?.querySelector("[role=combobox]")).toBeNull();
  expect(dialog()?.querySelector("[role=listbox]")).not.toBeNull();
  expect(options().some((row) => row.textContent?.includes("claude-opus-5-5"))).toBe(true);
  expect(options()[0].getAttribute("aria-selected")).toBe("false");
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(search(), "embed"); search().dispatchEvent(new Event("input", { bubbles: true })); });
  expect(options()).toHaveLength(1);
  expect(options()[0].textContent).toContain("embed-model");
});

it("supports all task categories, counts, and family mode", async () => {
  await show({ suggested: ["claude-haiku-4-5"], provider: "openrouter" }); await click(pickerInput());
  const nav = dialog()!;
  for (const category of ["All models", "Suggested", "General", "Reasoning", "Code", "Vision", "Embeddings"]) expect(nav.textContent).toContain(category);
  const code = [...nav.querySelectorAll("button")].find((button) => button.textContent?.startsWith("Code"))!;
  await click(code);
  expect(options().map((row) => row.textContent)).toEqual([expect.stringContaining("code-model")]);
  await click([...nav.querySelectorAll("[role=tab]")].find((tab) => tab.textContent === "By family")!);
  expect(nav.textContent).toContain("Claude");
  expect(nav.textContent).toContain("Embeddings");
  await click([...nav.querySelectorAll("button")].find((button) => button.textContent?.startsWith("Embeddings"))!);
  expect(options()[0].textContent).toContain("embed-model");
});

it("preserves free-text ids and applies direct use without requiring a catalog row", async () => {
  await show(); await click(pickerInput());
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(search(), "vendor/new-model"); search().dispatchEvent(new Event("input", { bubbles: true })); });
  expect(dialog()?.textContent).toContain("No models match");
  await click([...dialog()!.querySelectorAll("button")].find((button) => button.textContent?.includes("Use") && button.textContent?.includes("directly"))!);
  expect(currentValue).toBe("vendor/new-model");
  expect(dialog()).toBeNull();
});

it("clears the browser search when the modal closes and reopens", async () => {
  await show(); await click(pickerInput());
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(search(), "embed"); search().dispatchEvent(new Event("input", { bubbles: true })); });
  expect(options()).toHaveLength(1);
  await click([...dialog()!.querySelectorAll("button")].find((button) => button.textContent?.includes("Cancel"))!);
  await act(async () => { await new Promise((resolve) => requestAnimationFrame(() => resolve(undefined))); });
  await click(pickerInput());
  expect(search().value).toBe("");
  expect(options()).toHaveLength(catalog.models.length);
});

it("selects a row, marks it selected, and closes", async () => {
  await show({ initial: "claude-haiku-4-5" }); await click(pickerInput());
  expect(options().find((row) => row.textContent?.includes("claude-haiku-4-5"))?.getAttribute("aria-selected")).toBe("true");
  await click(options()[0]);
  expect(currentValue).toBe("claude-opus-5-5");
  expect(dialog()).toBeNull();
});

it("keeps normal Tab traversal inside the modal and Escape restores focus to the picker input", async () => {
  await show(); await click(pickerInput());
  expect(document.activeElement).toBe(search());
  expect(pickerInput().getAttribute("aria-controls")).toBe(dialog()?.id);
  const buttons = [...dialog()!.querySelectorAll("button")];
  const first = buttons[0];
  const cancel = buttons.find((button) => button.textContent?.includes("Cancel"))!;
  cancel.focus();
  await key(cancel, "Tab");
  expect(document.activeElement).toBe(first);
  await key(first, "Tab");
  expect(dialog()).not.toBeNull();
  expect(document.activeElement).not.toBe(pickerInput());
  await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect(dialog()).toBeNull();
  await act(async () => { await new Promise((resolve) => requestAnimationFrame(() => resolve(undefined))); });
  expect(document.activeElement).toBe(pickerInput());
});

it("wraps Shift+Tab from the first modal control to the last control", async () => {
  await show(); await click(pickerInput());
  const buttons = [...dialog()!.querySelectorAll("button")];
  const first = buttons[0];
  const cancel = buttons.find((button) => button.textContent?.includes("Cancel"))!;
  first.focus();
  await key(first, "Tab", { shiftKey: true });
  expect(document.activeElement).toBe(cancel);
});

it("announces loading, stale, empty, and error states and supports retry", async () => {
  let resolve: ((value: ModelsOut) => void) | undefined;
  vi.mocked(Api.getModels).mockImplementation(() => new Promise((r) => { resolve = r; }));
  await show(); await click(pickerInput());
  expect(dialog()?.querySelector("[role=status]")?.textContent).toContain("Loading models");
  resolve!(catalog);
  await until(() => dialog()?.querySelector("[role=status]")?.textContent?.includes("models available") === true, "catalog did not resolve");

  vi.mocked(Api.getModels).mockRejectedValueOnce(new Error("network down"));
  await qc.resetQueries({ queryKey: ["models", "anthropic"] });
  await act(async () => { await root.render(<QueryClientProvider client={qc}><Host /></QueryClientProvider>); });
  await click(pickerInput());
  await until(() => dialog()?.querySelector("[role=alert]") !== null, "error state did not render");
  expect(dialog()?.querySelector("[role=alert]")?.textContent).toContain("could not be loaded");
  expect(dialog()?.querySelector("[role=status]")?.textContent).toContain("could not be loaded");
  vi.mocked(Api.getModels).mockResolvedValue(catalog);
  await click([...dialog()!.querySelectorAll("button")].find((button) => button.textContent === "Retry")!);
  await until(() => options().length > 0, "retry did not restore model options");
});

it("shows stale refresh affordance, selected contrast hooks, metadata hierarchy, and touch spacing", async () => {
  vi.mocked(Api.getModels).mockResolvedValue({ ...catalog, stale: true });
  await show({ initial: "claude-opus-5-5" }); await click(pickerInput());
  expect(dialog()?.textContent).toContain("Catalog may be out of date");
  const selected = options().find((row) => row.getAttribute("aria-selected") === "true")!;
  expect(selected.className).toContain("bg-accent");
  expect(selected.className).toContain("min-h-12");
  expect(selected.textContent).toContain("Most capable reasoning model");
  expect(selected.textContent).toContain("effort");
});

it("shows unconfigured providers without blocking direct entry", async () => {
  vi.mocked(Api.getModels).mockResolvedValue({ ...catalog, configured: false, models: [] });
  await show({ initial: "custom/model" }); await click(pickerInput());
  expect(dialog()?.textContent).toContain("Anthropic is not configured");
  expect(dialog()?.querySelector("[role=listbox]")).toBeNull();
  expect(dialog()?.querySelector("[role=status]")?.textContent).toContain("not configured");
});

it("shows the full OpenRouter catalog regardless of which direct provider keys are configured", async () => {
  vi.spyOn(Api, "getModels").mockResolvedValue({ ...catalog, provider: "openrouter", models: [model("openai/gpt-5"), model("google/gemini-3"), model("openrouter/auto")] });
  vi.spyOn(Api, "getProviders").mockResolvedValue({ providers: [{ id: "auto", configured: true, models: [], default_model: "" }, { id: "openrouter", configured: true, models: [], default_model: "" }, { id: "openai", configured: false, models: [], default_model: "" }], embedding_model: "", embeddings_configured: false });
  await show({ provider: "openrouter" }); await click(pickerInput());
  expect(options().map((row) => row.querySelector(".font-mono")?.textContent).sort()).toEqual(["google/gemini-3", "openai/gpt-5", "openrouter/auto"]);
  const vendor = dialog()!.querySelector<HTMLSelectElement>("select[aria-label='Model vendor']")!;
  expect([...vendor.options].map((o) => o.value)).toEqual(["", "google", "openai", "openrouter"]);
  await act(async () => { vendor.value = "google"; vendor.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(options().map((row) => row.querySelector(".font-mono")?.textContent)).toEqual(["google/gemini-3"]);
});

it("sorts a task by leaderboard rank by default and cycles through newest and cheapest", async () => {
  vi.spyOn(Api, "getModels").mockResolvedValue({ ...catalog, provider: "openrouter", models: [
    model("a/new-coder", { description: "coding", release_date: "2026-09-01", cost_output: 9 }),
    model("b/top-coder", { release_date: "2025-01-01", cost_output: 5, task_ranks: { Code: 1 } }),
    model("c/cheap-coder", { description: "coding", release_date: "2026-01-01", cost_output: 1, task_ranks: { Code: 2 } }),
  ] });
  await show({ provider: "openrouter" }); await click(pickerInput());
  await click([...dialog()!.querySelectorAll("button")].find((b) => b.textContent?.startsWith("Code"))!);
  const ids = () => options().map((row) => row.querySelector(".font-mono")?.textContent);
  const sortButton = () => dialog()!.querySelector<HTMLButtonElement>("button[aria-label='Sort models']")!;
  expect(sortButton().textContent).toBe("Sort: Top ranked");
  expect(ids()).toEqual(["b/top-coder", "c/cheap-coder", "a/new-coder"]);
  expect(options()[0].querySelector("[data-rank=Code]")?.textContent).toBe("#1 code");
  expect(options()[2].querySelector("[data-rank]")).toBeNull();
  await click(sortButton());
  expect(sortButton().textContent).toBe("Sort: Newest");
  expect(ids()).toEqual(["a/new-coder", "c/cheap-coder", "b/top-coder"]);
  await click(sortButton());
  expect(sortButton().textContent).toBe("Sort: Cheapest");
  expect(ids()).toEqual(["c/cheap-coder", "b/top-coder", "a/new-coder"]);
  await click(sortButton());
  expect(sortButton().textContent).toBe("Sort: Top ranked");
});

it("offers no rank sort when the catalog has no leaderboard data", async () => {
  await show(); await click(pickerInput());
  const sortButton = dialog()!.querySelector<HTMLButtonElement>("button[aria-label='Sort models']")!;
  expect(sortButton.textContent).toBe("Sort: Newest");
  await click(sortButton);
  expect(sortButton.textContent).toBe("Sort: Cheapest");
  await click(sortButton);
  expect(sortButton.textContent).toBe("Sort: Newest");
});
