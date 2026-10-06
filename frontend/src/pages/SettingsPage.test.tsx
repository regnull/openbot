// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Api } from "../api/client";
import type { AppSetting } from "../api/types";
import SettingsPage from "./SettingsPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root; let el: HTMLDivElement; let qc: QueryClient;
const setting = (key: string, value: unknown, extra: Partial<AppSetting> = {}): AppSetting => ({
  key, group: "Model routing", label: key, description: "", type: "str", value, default: value, overridden: false, secret: false, is_set: true, ...extra,
});
const settings = [setting("bot_model", "openai/gpt-4o-mini"), setting("openrouter_provider_order", "")];
async function tick() { await act(async () => { await new Promise((r) => setTimeout(r, 20)); }); }
async function until(condition: () => boolean) {
  const deadline = Date.now() + 2000;
  while (!condition()) { if (Date.now() > deadline) throw new Error("Timed out"); await tick(); }
}
const combobox = () => el.querySelector<HTMLInputElement>("input[role=combobox]");
/** The Save button of the card that holds `node` (the API-key card has its own, always-enabled Save). */
function saveButtonFor(node: Element): HTMLButtonElement {
  for (let n: Element | null = node; n; n = n.parentElement) {
    const b = [...n.querySelectorAll("button")].find((x) => x.textContent === "Save");
    if (b) return b;
  }
  throw new Error("no Save button above the picker");
}

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(Api, "getSettings").mockResolvedValue(settings);
  vi.spyOn(Api, "getProviders").mockResolvedValue({ providers: [], embedding_model: "none", embeddings_configured: false });
  vi.spyOn(Api, "listTools").mockResolvedValue({ tools: [], errors: [] });
  vi.spyOn(Api, "listActors").mockResolvedValue([]);
  vi.spyOn(Api, "listMcpServers").mockResolvedValue([]);
  vi.spyOn(Api, "listMcpCatalog").mockResolvedValue([]);
  vi.spyOn(Api, "getDatabaseLocation").mockResolvedValue({ location: "/tmp" });
  vi.spyOn(Api, "getModels").mockResolvedValue({ provider: "openrouter", configured: true, source: "catalog", stale: false, fetched_at: "2026-09-27T00:00:00Z", models: [
    { id: "z-ai/glm-5.3-flash", name: "GLM 5.3 Flash", family: "glm-flash", description: "", reasoning: true, effort_levels: ["low", "high"], image_input: false, context: 200000, output: null, cost_input: 0.1, cost_output: 0.3, release_date: "2026-04-01", status: null },
  ] });
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(async () => { await act(async () => root.unmount()); el.remove(); qc.clear(); vi.restoreAllMocks(); });

it("renders the default bot model as an OpenRouter catalog picker and saves the picked value", async () => {
  const patch = vi.spyOn(Api, "patchSettings").mockImplementation(async (updates) => settings.map((s) => (s.key in updates ? { ...s, value: updates[s.key], overridden: true } : s)));
  await act(async () => root.render(<QueryClientProvider client={qc}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>));
  await until(() => combobox() !== null);
  expect(combobox()!.value).toBe("openai/gpt-4o-mini");
  expect(Api.getModels).toHaveBeenCalledWith("openrouter");

  // Focusing the combobox opens the panel over the whole catalog (it no longer filters by the field's
  // current value), so the picker lists z-ai/glm-5.3-flash even though the field still holds the saved id.
  await act(async () => { combobox()!.focus(); });
  await until(() => document.body.querySelector("[role=option]") !== null);
  await act(async () => { document.body.querySelector<HTMLElement>("[role=option]")!.click(); });
  expect(combobox()!.value).toBe("z-ai/glm-5.3-flash");
  const save = saveButtonFor(combobox()!);
  expect(save.disabled).toBe(false);
  await act(async () => { save.click(); });
  await until(() => patch.mock.calls.length > 0);
  expect(patch.mock.calls[0][0]).toEqual({ bot_model: "z-ai/glm-5.3-flash" });
});
