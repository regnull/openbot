// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Api } from "../api/client";
import type { AppSetting, Bot, McpServer } from "../api/types";
import SaveNotification from "../components/SaveNotification";
import { dismissSaveNotification } from "../lib/saveNotifications";
import SettingsPage from "./SettingsPage";
import BotEditorPage from "./BotEditorPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let el: HTMLDivElement;
let qc: QueryClient;
const row: AppSetting = { key: "limit", group: "Run limits", label: "Limit", description: "", type: "int", value: 10, default: 5, overridden: true, secret: false, is_set: true };
const bot: Bot = { id: "b1", name: "Bot", handle: "bot", description: "", icon: "bot", instructions: "", provider: "auto", model: "", model_settings: {}, tool_names: [], approval_tools: [], memory_enabled: true, enabled: true, active: false, created_at: "", updated_at: "" };
const notice = () => el.querySelector('[role="status"]')!.textContent;
const button = (text: string, parent: ParentNode = el) => [...parent.querySelectorAll("button")].find((b) => b.textContent === text)!;
const click = async (b: HTMLButtonElement) => { await act(async () => b.click()); };
async function until(condition: () => boolean) {
  const deadline = Date.now() + 2000;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error(`Timed out: ${el.textContent}`);
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
  }
}
async function input(node: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function mount(path = "/settings") {
  await act(async () => root.render(
    <QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}>
      <SaveNotification /><Routes>
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/edit/:id" element={<BotEditorPage />} />
        <Route path="/bots/new" element={<BotEditorPage />} />
        <Route path="/bots/:id" element={<p>Saved bot destination</p>} />
      </Routes>
    </MemoryRouter></QueryClientProvider>,
  ));
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  dismissSaveNotification(); localStorage.clear();
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  qc.setQueryData(["settings"], [row]);
  qc.setQueryData(["providers"], { providers: [], embedding_model: "none", embeddings_configured: false });
  qc.setQueryData(["tools"], { tools: [], errors: [] });
  qc.setQueryData(["actors"], []); qc.setQueryData(["mcp-servers"], []);
  qc.setQueryData(["bot", "b1"], bot);
  vi.spyOn(Api, "getSettings").mockResolvedValue([row]);
  vi.spyOn(Api, "getProviders").mockResolvedValue({ providers: [], embedding_model: "none", embeddings_configured: false });
  vi.spyOn(Api, "listTools").mockResolvedValue({ tools: [], errors: [] });
  vi.spyOn(Api, "listActors").mockResolvedValue([]);
  vi.spyOn(Api, "listMcpServers").mockResolvedValue([]);
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(async () => {
  await act(async () => root.unmount());
  el.remove(); qc.clear(); dismissSaveNotification(); vi.restoreAllMocks();
});

it.each([true, false])("runtime settings only confirm persisted saves (success=%s)", async (success) => {
  const pending = deferred<AppSetting[]>();
  const save = vi.spyOn(Api, "patchSettings").mockReturnValue(pending.promise);
  await mount();
  await input(el.querySelector('input[inputmode="decimal"]')!, "20");
  await click(button("Save"));
  expect(save).toHaveBeenCalledExactlyOnceWith({ limit: 20 });
  expect(notice()).toBe("");
  expect(button("Saving…").disabled).toBe(true);
  await click(button("Saving…"));
  expect(save).toHaveBeenCalledTimes(1);
  await act(async () => { if (success) pending.resolve([{ ...row, value: 20 }]); else pending.reject(new Error("Persistence failed")); });
  await until(() => !!notice());
  expect(notice()).toContain(success ? "Settings saved" : "Could not save changes");
  if (!success) { expect(notice()).not.toContain("Settings saved"); await until(() => !!el.textContent?.includes("Persistence failed")); }
  await act(async () => qc.invalidateQueries({ queryKey: ["settings"] }));
  expect(el.querySelectorAll('[aria-label="Dismiss notification"]')).toHaveLength(1);
});

it("confirms a setting reset", async () => {
  vi.spyOn(Api, "resetSetting").mockResolvedValue([{ ...row, value: 5, overridden: false }]);
  await mount(); await click(button("reset to 5"));
  await until(() => !!notice()); expect(notice()).toContain("Setting reset to default");
});

it.each([true, false])("bot edit reports persistence result across navigation (success=%s)", async (success) => {
  const pending = deferred<Bot>();
  vi.spyOn(Api, "updateBot").mockReturnValue(pending.promise);
  await mount("/edit/b1");
  await act(async () => el.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(notice()).toBe("");
  await act(async () => { if (success) pending.resolve(bot); else pending.reject(new Error("Bot save failed")); });
  await until(() => !!notice());
  expect(notice()).toContain(success ? "Bot settings saved" : "Could not save changes");
  expect(el.textContent?.includes("Saved bot destination")).toBe(success);
});

it.each([true, false])("MCP add confirms only persistence, not connection (success=%s)", async (success) => {
  const pending = deferred<McpServer>();
  vi.spyOn(Api, "addMcpServer").mockReturnValue(pending.promise);
  await mount(); await click(button("Add server"));
  const dialog = el.querySelector('[role="dialog"]')!;
  await input(dialog.querySelector('input[placeholder="Name"]')!, "test");
  await input(dialog.querySelector('input[placeholder="MCP server URL"]')!, "https://example.com/mcp");
  await act(async () => dialog.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(notice()).toBe("");
  await act(async () => { if (success) pending.resolve({ status: "connecting" } as McpServer); else pending.reject(new Error("MCP save failed")); });
  await until(() => !!notice());
  expect(notice()).toContain(success ? "MCP server added" : "Could not save changes");
  expect(!!el.querySelector('[role="dialog"]')).toBe(!success);
});

it.each([true, false])("browser API key persistence reports storage failures (success=%s)", async (success) => {
  if (!success) vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage blocked"); });
  await mount();
  const key = el.querySelector<HTMLInputElement>('input[placeholder="X-API-Key"]')!;
  await input(key, " secret "); await click(button("Save", key.parentElement!));
  expect(notice()).toContain(success ? "API key saved in this browser" : "Could not save the API key");
  expect(localStorage.getItem("openbot_api_key")).toBe(success ? "secret" : null);
});
