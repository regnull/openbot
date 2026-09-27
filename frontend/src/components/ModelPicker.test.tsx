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
const catalog: ModelsOut = { provider: "anthropic", source: "catalog", stale: false, fetched_at: "2026-09-27T00:00:00Z", models: [
  model("claude-opus-5-5", { name: "Claude Opus 5.5", family: "claude-opus", description: "Most capable", reasoning: true, effort_levels: ["low", "high"], image_input: true, cost_input: 5, cost_output: 25, release_date: "2026-03-01" }),
  model("claude-haiku-4-5", { name: "Claude Haiku 4.5", family: "claude-haiku", release_date: "2025-10-15" }),
] };

let root: Root; let el: HTMLDivElement; let qc: QueryClient; let last = "";
function Host({ initial = "", suggested = [] as string[], provider = "anthropic", suggestedLabel = "Suggested" }) {
  const [v, setV] = useState(initial);
  last = v;
  return <ModelPicker provider={provider} value={v} onChange={setV} suggested={suggested} suggestedLabel={suggestedLabel} />;
}
async function show(props: Parameters<typeof Host>[0] = {}) {
  await act(async () => root.render(<QueryClientProvider client={qc}><Host {...props} /></QueryClientProvider>));
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
}
const input = () => el.querySelector<HTMLInputElement>("input[role=combobox]")!;
const options = () => [...el.querySelectorAll<HTMLElement>("[role=option]")].map((o) => o.querySelector("span")!.textContent);
const groupLabels = () => [...el.querySelectorAll<HTMLElement>("[data-group]")].map((g) => g.dataset.group);
// jsdom fires no focus event on an element that already has focus, so blur first to reopen the panel.
const focus = () => act(async () => { input().blur(); input().focus(); });
async function type(text: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input(), text);
    input().dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const key = (k: string) => act(async () => { input().dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true })); });
const press = (elm: Element) => act(async () => { elm.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true })); elm.dispatchEvent(new MouseEvent("click", { bubbles: true })); });

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(Api, "getModels").mockResolvedValue(catalog);
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(async () => { await act(async () => root.unmount()); el.remove(); qc.clear(); vi.restoreAllMocks(); });

it("opens on focus, lists the catalog grouped by family newest first, and filters as you type", async () => {
  await show();
  expect(el.querySelector("[role=listbox]")).toBeNull();
  await focus();
  expect(options()).toEqual(["claude-opus-5-5", "claude-haiku-4-5"]);
  expect(groupLabels()).toEqual(["claude-opus", "claude-haiku"]);
  await type("HAIKU");
  expect(options()).toEqual(["claude-haiku-4-5"]);
  expect(last).toBe("HAIKU");
});

it("keeps free text as the value and notes it is not in the catalog", async () => {
  await show();
  await focus();
  await type("my-custom-model");
  expect(last).toBe("my-custom-model");
  expect(options()).toEqual([]);
  expect(el.textContent).toContain("No matching models");
  expect(el.textContent).toContain("Not in the catalog");
  await type("claude-opus-5-5");
  expect(el.textContent).not.toContain("Not in the catalog");
});

it("picks with the keyboard and closes; Escape closes without picking", async () => {
  await show();
  await focus();
  await key("ArrowDown");
  await key("Enter");
  expect(last).toBe("claude-haiku-4-5");
  expect(el.querySelector("[role=listbox]")).toBeNull();
  await focus();
  await key("Escape");
  expect(el.querySelector("[role=listbox]")).toBeNull();
  expect(last).toBe("claude-haiku-4-5");
});

it("picks with the mouse, shows cost and badges, and the chips narrow the list", async () => {
  await show();
  await focus();
  const opus = el.querySelectorAll("[role=option]")[0];
  expect(opus.textContent).toContain("$5 / $25 per M tokens");
  expect(opus.textContent).toContain("effort");
  expect(opus.textContent).toContain("200k");
  expect(opus.textContent).toContain("Most capable");
  await press(el.querySelector("button[aria-pressed][data-chip=reasoning]")!);
  expect(options()).toEqual(["claude-opus-5-5"]);
  await press(el.querySelectorAll("[role=option]")[0]);
  expect(last).toBe("claude-opus-5-5");
});

it("pins suggested ids first under the given label and marks Ollama rows that are not installed", async () => {
  await show({ provider: "ollama", suggested: ["qwen3:8b", "claude-haiku-4-5"], suggestedLabel: "Installed" });
  await focus();
  expect(groupLabels()[0]).toBe("Installed");
  expect(options()).toEqual(["qwen3:8b", "claude-haiku-4-5", "claude-opus-5-5"]);
  const rows = el.querySelectorAll("[role=option]");
  expect(rows[0].textContent).not.toContain("not installed");
  expect(rows[1].textContent).toContain("on Ollama Cloud");
  expect(rows[2].textContent).toContain("not installed");
});

it("shows the updating hint when the catalog is stale or builtin", async () => {
  vi.mocked(Api.getModels).mockResolvedValue({ ...catalog, source: "builtin", stale: true, fetched_at: null, models: [model("gpt-5.5", { context: null, cost_input: null, cost_output: null })] });
  await show();
  await focus();
  expect(el.textContent).toContain("Catalog updating");
  expect(options()).toEqual(["gpt-5.5"]);
});
