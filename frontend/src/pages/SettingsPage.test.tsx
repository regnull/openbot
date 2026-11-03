// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Api } from "../api/client";
import type { AppSetting, Bot, McpServer } from "../api/types";
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

const mcpServer = (tools: string[]): McpServer => ({ name: "lin", transport: "http", status: tools.length ? "connected" : "disconnected", enabled: true, oauth: false,
  url: "https://mcp.example.com/mcp", error: null, tools, source: "db", authorization_url: null, command: null, args: [], cwd: null, env: {}, headers: {} });
const bot = (id: string, tool_names: string[], approval_tools: string[] = []): Bot => ({ id, handle: id, name: `Bot ${id}`, description: "", icon: "bot", enabled: true, active: false,
  instructions: "", provider: "auto", model: "", model_settings: {}, tool_names, approval_tools, skill_names: [], memory_enabled: true, created_at: "", updated_at: "" });
const grantBox = (handle: string) => document.body.querySelector<HTMLInputElement>(`input[aria-label="Grant lin to @${handle}"]`);
const dialogButton = (label: string) => [...document.getElementById("mcp-dialog-title")!.closest("form")!.querySelectorAll("button")].find((b) => b.textContent === label)!;
async function editServer() {
  await act(async () => root.render(<QueryClientProvider client={qc}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>));
  await until(() => [...el.querySelectorAll("button")].some((b) => b.textContent === "Edit"));
  await act(async () => { [...el.querySelectorAll("button")].find((b) => b.textContent === "Edit")!.click(); });
}

it("grants or clears a server's tools for several bots from its edit dialog", async () => {
  const tools = ["lin__create_issue", "lin__list_issues"];
  vi.mocked(Api.listMcpServers).mockResolvedValue([mcpServer(tools)]);
  vi.spyOn(Api, "listBots").mockResolvedValue([
    bot("all", ["run_shell", ...tools], ["lin__create_issue"]), bot("some", ["lin__list_issues"]), bot("none", ["run_shell"]),
  ]);
  const updateBot = vi.spyOn(Api, "updateBot").mockImplementation(async (id) => bot(id, []));
  const updateServer = vi.spyOn(Api, "updateMcpServer").mockResolvedValue(mcpServer(tools));
  await editServer();
  await until(() => grantBox("none") !== null);
  expect([grantBox("all")!.checked, grantBox("some")!.checked, grantBox("some")!.indeterminate, grantBox("none")!.checked]).toEqual([true, false, true, false]);
  expect(document.body.textContent).toContain("1 of 2");

  await act(async () => { grantBox("all")!.click(); });
  await act(async () => { grantBox("some")!.click(); });
  expect([grantBox("all")!.checked, grantBox("some")!.checked]).toEqual([false, true]);
  await act(async () => { dialogButton("Save").click(); });
  await until(() => updateServer.mock.calls.length > 0);
  expect(updateBot.mock.calls).toEqual([
    ["all", { tool_names: ["run_shell"], approval_tools: [] }],
    ["some", { tool_names: ["lin__list_issues", "lin__create_issue"], approval_tools: [] }],
  ]);
});

it("asks to connect a server without tools before granting it to bots, and lists no bots when adding one", async () => {
  vi.mocked(Api.listMcpServers).mockResolvedValue([mcpServer([])]);
  const listBots = vi.spyOn(Api, "listBots").mockResolvedValue([bot("b1", [])]);
  await editServer();
  await until(() => document.body.textContent!.includes("Connect the server to grant its tools to bots here."));
  expect(grantBox("b1")).toBeNull();

  listBots.mockClear();
  await act(async () => { dialogButton("Cancel").click(); });
  await act(async () => { [...el.querySelectorAll("button")].find((b) => b.textContent === "Add server")!.click(); });
  await until(() => document.body.textContent!.includes("Add MCP server"));
  expect(document.body.textContent).not.toContain("Bots with this server's tools");
  expect(listBots).not.toHaveBeenCalled();
});
