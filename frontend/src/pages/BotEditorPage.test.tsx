// @vitest-environment jsdom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Api } from "../api/client";
import type { Bot, CatalogModel, ModelsOut, ProvidersOut } from "../api/types";
import BotEditorPage from "./BotEditorPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let el: HTMLDivElement;
let qc: QueryClient;
const bot = (id: string, name: string): Bot => ({ id, name, handle: id, description: "", icon: "bot", instructions: "", provider: "auto", model: "", model_settings: {}, tool_names: [], approval_tools: [], memory_enabled: true, enabled: true, active: false, created_at: "", updated_at: "" });
const model = (id: string, extra: Partial<CatalogModel> = {}): CatalogModel => ({
  id, name: id, family: "", description: "", reasoning: false, effort_levels: [], image_input: false, context: 200000, output: null,
  cost_input: 1, cost_output: 5, release_date: "2026-01-01", status: null, ...extra,
});
const catalog: ModelsOut = { provider: "anthropic", configured: true, source: "catalog", stale: false, fetched_at: "2026-09-27T00:00:00Z", models: [
  model("claude-opus-5-5", { family: "claude-opus", reasoning: true, effort_levels: ["low", "high"] }),
  model("claude-haiku-4-5", { family: "claude-haiku" }),
] };
const providers: ProvidersOut = { embedding_model: "none", embeddings_configured: false, providers: [
  { id: "auto", configured: true, models: [], default_model: "anthropic/claude-opus-5-5" },
  { id: "anthropic", configured: true, models: ["claude-opus-5-5"], default_model: "claude-opus-5-5" },
  { id: "openrouter", configured: false, models: [], default_model: "" },
] };
const nameInput = () => el.querySelector<HTMLInputElement>("input[required]")?.value;
const effortSelect = () => el.querySelector<HTMLSelectElement>("select[aria-label=Effort]");
const submit = () => act(async () => { el.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
async function until(condition: () => boolean) {
  const deadline = Date.now() + 2000;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error(`Timed out: name=${nameInput()}`);
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
  }
}
// Navigates inside the router, so the editor instance is reused like when switching bots in the app.
function Go({ to }: { to: string }) {
  const nav = useNavigate();
  useEffect(() => { nav(to); }, [nav, to]);
  return null;
}
async function show(path: string) {
  await act(async () => root.render(
    <QueryClientProvider client={qc}><MemoryRouter initialEntries={["/edit/b1"]}>
      <Go to={path} />
      <Routes><Route path="/edit/:id" element={<BotEditorPage />} /></Routes>
    </MemoryRouter></QueryClientProvider>,
  ));
}
beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  vi.spyOn(Api, "getProviders").mockResolvedValue({ providers: [], embedding_model: "none", embeddings_configured: false });
  vi.spyOn(Api, "listTools").mockResolvedValue({ tools: [], errors: [] });
  vi.spyOn(Api, "getBot").mockImplementation((id: string) => Promise.resolve(bot(id, `Bot ${id}`)));
  vi.spyOn(Api, "getModels").mockResolvedValue(catalog);
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(async () => {
  await act(async () => root.unmount());
  el.remove(); qc.clear(); vi.restoreAllMocks();
});

it("reloads the form when switching to another bot on the same page", async () => {
  await show("/edit/b1");
  await until(() => nameInput() === "Bot b1");

  await show("/edit/b2");
  await until(() => nameInput() === "Bot b2");

  // Back to a bot that is already cached: its settings come back, not the ones just shown.
  await show("/edit/b1");
  await until(() => nameInput() === "Bot b1");
  expect(Api.getBot).toHaveBeenCalledTimes(2);
});

it("offers effort levels only for models that declare them, including the auto provider's resolved model", async () => {
  vi.mocked(Api.getProviders).mockResolvedValue(providers);
  vi.spyOn(Api, "getBot").mockImplementation((id: string) => Promise.resolve(
    id === "b1" ? { ...bot("b1", "Opus"), provider: "anthropic", model: "claude-opus-5-5", model_settings: { reasoning_effort: "high" } }
    : id === "b2" ? { ...bot("b2", "Haiku"), provider: "anthropic", model: "claude-haiku-4-5" }
    : { ...bot("b3", "Auto"), provider: "auto", model: "" }));
  await show("/edit/b1");
  await until(() => effortSelect() !== null);
  expect([...effortSelect()!.options].map((o) => o.value)).toEqual(["", "low", "high"]);
  expect(effortSelect()!.value).toBe("high");

  await show("/edit/b2");
  await until(() => nameInput() === "Haiku");
  expect(effortSelect()).toBeNull();

  await show("/edit/b3");
  await until(() => nameInput() === "Auto");
  await until(() => effortSelect() !== null);
  expect(effortSelect()!.value).toBe("");
});

it("drops an effort the model does not accept on save and removes the key when Default is chosen", async () => {
  vi.mocked(Api.getProviders).mockResolvedValue(providers);
  vi.spyOn(Api, "getBot").mockResolvedValue({ ...bot("b1", "Stale"), provider: "anthropic", model: "claude-haiku-4-5", model_settings: { reasoning_effort: "high", web_search: true } });
  const update = vi.spyOn(Api, "updateBot").mockImplementation(async (id, b) => ({ ...bot(id, "Stale"), ...b } as Bot));
  await show("/edit/b1");
  await until(() => nameInput() === "Stale");
  await until(() => !el.textContent?.includes("Not in the catalog"));
  await submit();
  await until(() => update.mock.calls.length > 0);
  expect(update.mock.calls[0][1].model_settings).toEqual({ web_search: true });

  vi.spyOn(Api, "getBot").mockResolvedValue({ ...bot("b2", "Opus"), provider: "anthropic", model: "claude-opus-5-5", model_settings: { reasoning_effort: "low" } });
  await show("/edit/b2");
  await until(() => effortSelect() !== null && effortSelect()!.value === "low");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(effortSelect()!, "");
    effortSelect()!.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await submit();
  await until(() => update.mock.calls.length > 1);
  expect(update.mock.calls[1][1].model_settings).toEqual({});
});

it("uses the catalog picker for catalog providers and warns when OpenRouter reroutes cloud bots", async () => {
  vi.mocked(Api.getProviders).mockResolvedValue({ ...providers, providers: providers.providers.map((p) => (p.id === "openrouter" ? { ...p, configured: true } : p)) });
  vi.spyOn(Api, "getBot").mockResolvedValue({ ...bot("b1", "Opus"), provider: "anthropic", model: "claude-opus-5-5" });
  await show("/edit/b1");
  await until(() => el.querySelector("input[role=combobox]") !== null);
  expect(el.querySelector<HTMLInputElement>("input[role=combobox]")!.value).toBe("claude-opus-5-5");
  expect(el.textContent).toContain("With an OpenRouter key configured");
});
