// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import BotPage, { purgeSummary } from "./BotPage";
import type { Bot } from "../api/types";

const fake = vi.hoisted(() => ({ api: {} as Record<string, (...args: never[]) => unknown> }));
vi.mock("../api/client", () => ({ Api: fake.api }));

const bot: Bot = {
  id: "b1", handle: "eng", name: "Engineer", description: "", icon: "robot", enabled: true, active: true, instructions: "",
  provider: "auto", model: "", model_settings: {}, tool_names: [], approval_tools: [], memory_enabled: true, created_at: "", updated_at: "",
};

describe("purgeSummary", () => {
  it("reads naturally for zero, one and many", () => {
    expect(purgeSummary({ cancelled_runs: 0, purged_items: 0 })).toBe("Nothing to cancel: no open run and an empty queue.");
    expect(purgeSummary({ cancelled_runs: 1, purged_items: 1 })).toBe("Cancelled 1 run, dropped 1 queued item.");
    expect(purgeSummary({ cancelled_runs: 2, purged_items: 3 })).toBe("Cancelled 2 runs, dropped 3 queued items.");
  });
});

describe("BotPage cancel & purge", () => {
  let root: Root;
  let el: HTMLDivElement;
  let purgeCalls: string[];
  let confirmed: boolean;
  const text = (): string => el.textContent ?? "";
  const until = async (cond: () => boolean, what: string): Promise<void> => {
    const deadline = Date.now() + 2_000;
    while (!cond()) {
      if (Date.now() > deadline) throw new Error(`timeout waiting for ${what}; page text: ${text().slice(0, 300)}`);
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    }
  };
  const button = (): HTMLButtonElement => {
    const b = Array.from(el.querySelectorAll("button")).find((x) => x.textContent?.includes("Cancel & purge"));
    if (!b) throw new Error("no purge button");
    return b;
  };

  beforeEach(async () => {
    purgeCalls = [];
    confirmed = true;
    vi.stubGlobal("confirm", () => confirmed);
    fake.api.getBot = () => Promise.resolve(bot) as never;
    fake.api.getBotInbox = () => Promise.resolve([]) as never;
    fake.api.purgeBot = (id: string) => { purgeCalls.push(id); return Promise.resolve({ cancelled_runs: 1, purged_items: 2 }) as never; };
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    el = document.createElement("div");
    document.body.appendChild(el);
    root = createRoot(el);
    await act(async () => {
      root.render(
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={["/bots/b1"]}>
            <Routes><Route path="/bots/:id" element={<BotPage />} /></Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });
    await until(() => text().includes("@eng"), "bot header");
  });

  afterEach(() => {
    act(() => root.unmount());
    el.remove();
    vi.unstubAllGlobals();
  });

  it("asks first, then purges and reports what it did", async () => {
    await act(async () => { button().click(); });
    await until(() => purgeCalls.length === 1, "purge call");
    expect(purgeCalls).toEqual(["b1"]);
    await until(() => text().includes("Cancelled 1 run, dropped 2 queued items."), "purge summary");
  });

  it("does nothing when the confirmation is declined", async () => {
    confirmed = false;
    await act(async () => { button().click(); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    expect(purgeCalls).toEqual([]);
  });
});
