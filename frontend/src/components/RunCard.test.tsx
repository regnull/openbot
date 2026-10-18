// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RunCard from "./RunCard";
import { Api } from "../api/client";
import type { Run, RunEvent } from "../api/types";

vi.mock("../api/client", () => ({ Api: { getBotScratchpad: vi.fn() } }));

const run: Run = {
  id: "r", actor_id: "b1", thread_id: "t", status: "completed", interrupt: null, error: null,
  langsmith_run_id: null, created_at: "2026-01-01T00:00:00Z", started_at: null, finished_at: null,
};
const runWith = (actor_id: string): Run => ({ ...run, actor_id });
const ev = (seq: number, type: string, payload: Record<string, unknown>): RunEvent =>
  ({ id: `e${seq}`, run_id: "r", seq, type, payload, created_at: "2026-01-01T00:00:00Z" });

const render = (events: RunEvent[], r: Run = run) => {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const qc = new QueryClient();
  act(() => root.render(<QueryClientProvider client={qc}><RunCard run={r} events={events} botName="Engineer" /></QueryClientProvider>));
  return { container, cleanup: () => { act(() => root.unmount()); container.remove(); } };
};

describe("RunCard tool failures", () => {
  it("counts failed tool calls in the header and marks each one", () => {
    const { container, cleanup } = render([
      ev(1, "tool_call", { id: "a", name: "read_file", args: {} }),
      ev(2, "tool_result", { tool_call_id: "a", status: "success", content: "ok" }),
      ev(3, "tool_call", { id: "b", name: "Linear__save_comment", args: {} }),
      ev(4, "tool_result", { tool_call_id: "b", status: "error", content: "error: bad" }),
    ]);
    expect(container.textContent).toContain("2 tool calls · 1 failed");
    act(() => container.querySelector<HTMLButtonElement>("button")!.click());
    expect([...container.querySelectorAll("[title]")].map((e) => e.getAttribute("title"))).toEqual(["returned", "failed"]);
    cleanup();
  });

  it("says nothing about failures when every call succeeded", () => {
    const { container, cleanup } = render([
      ev(1, "tool_call", { id: "a", name: "read_file", args: {} }),
      ev(2, "tool_result", { tool_call_id: "a", status: "success", content: "ok" }),
    ]);
    expect(container.textContent).not.toContain("failed");
    cleanup();
  });
});

describe("RunCard scratchpad", () => {
  beforeEach(() => { vi.mocked(Api.getBotScratchpad).mockReset(); });

  /** Open the scratchpad section and let the fetch (or its failure) settle. */
  const openScratchpad = async (container: HTMLElement) => {
    const btn = [...container.querySelectorAll("button")].find((b) => b.textContent?.includes("scratchpad"));
    expect(btn, "scratchpad button").toBeTruthy();
    await act(async () => {
      btn!.click();
      await new Promise((r) => setTimeout(r, 0));
      await new Promise((r) => setTimeout(r, 0));
    });
  };

  it("lazily fetches and shows the pad on click, with the bot's name as context", async () => {
    vi.mocked(Api.getBotScratchpad).mockResolvedValue({ content: "State\n- step one done", updated_at: "2026-01-02T03:04:05Z" });
    const { container, cleanup } = render([], runWith("b2"));
    expect(container.textContent).toContain("Show scratchpad");
    expect(Api.getBotScratchpad).not.toHaveBeenCalled(); // lazy: nothing fetched before the click
    await openScratchpad(container);
    expect(Api.getBotScratchpad).toHaveBeenCalledWith("b2");
    expect(container.textContent).toContain("Engineer's scratchpad");
    expect(container.textContent).toContain("step one done");
    expect(container.textContent).not.toContain("Scratchpad is empty.");
    cleanup();
  });

  it("says so when the bot has never written a scratchpad", async () => {
    vi.mocked(Api.getBotScratchpad).mockResolvedValue({ content: "", updated_at: null });
    const { container, cleanup } = render([], runWith("b3"));
    await openScratchpad(container);
    expect(container.textContent).toContain("Scratchpad is empty.");
    cleanup();
  });

  it("shows an inline error (not a crash) when the fetch fails", async () => {
    vi.mocked(Api.getBotScratchpad).mockRejectedValue(new Error("boom"));
    const { container, cleanup } = render([], runWith("b4"));
    await openScratchpad(container);
    expect(container.textContent).toContain("boom");
    expect(container.textContent).not.toContain("Scratchpad is empty.");
    cleanup();
  });
});
