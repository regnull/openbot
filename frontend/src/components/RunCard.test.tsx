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
  beforeEach(() => { vi.mocked(Api.getBotScratchpad).mockResolvedValue({ content: "", updated_at: null }); });

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

  /** Let the scratchpad query (or its failure) settle. */
  const settle = () => act(async () => {
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
  });
  const padButton = (container: HTMLElement) => container.querySelector<HTMLButtonElement>('button[aria-label="Show scratchpad"]');

  it("shows an icon when the bot has a saved pad, and opens it in a dialog", async () => {
    vi.mocked(Api.getBotScratchpad).mockResolvedValue({ content: "State\n- step one done", updated_at: "2026-01-02T03:04:05Z" });
    const { container, cleanup } = render([], runWith("b2"));
    await settle();
    expect(Api.getBotScratchpad).toHaveBeenCalledWith("b2");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(container.textContent).not.toContain("step one done");
    await act(async () => { padButton(container)!.click(); });
    await settle();
    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain("Engineer's scratchpad");
    expect(dialog.textContent).toContain("step one done");
    expect(Api.getBotScratchpad).toHaveBeenCalledTimes(2); // opening refetches the latest write
    act(() => dialog.querySelector<HTMLButtonElement>('button[aria-label="Close"]')!.click());
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    cleanup();
  });

  it("shows no icon when the pad is empty or blank", async () => {
    vi.mocked(Api.getBotScratchpad).mockResolvedValue({ content: "  \n", updated_at: null });
    const { container, cleanup } = render([], runWith("b3"));
    await settle();
    expect(padButton(container)).toBeNull();
    cleanup();
  });

  it("shows no icon (and no crash) when the fetch fails", async () => {
    vi.mocked(Api.getBotScratchpad).mockRejectedValue(new Error("boom"));
    const { container, cleanup } = render([], runWith("b4"));
    await settle();
    expect(padButton(container)).toBeNull();
    expect(container.textContent).not.toContain("boom");
    cleanup();
  });

  it("refetches when a scratchpad save lands, so the icon appears mid-run", async () => {
    vi.mocked(Api.getBotScratchpad).mockResolvedValueOnce({ content: "", updated_at: null });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const qc = new QueryClient();
    const view = (events: RunEvent[]) => <QueryClientProvider client={qc}><RunCard run={runWith("b5")} events={events} /></QueryClientProvider>;
    const call = ev(1, "tool_call", { id: "s", name: "scratchpad", args: { action: "write", content: "x" } });
    act(() => root.render(view([call])));
    await settle();
    expect(padButton(container)).toBeNull();
    vi.mocked(Api.getBotScratchpad).mockResolvedValue({ content: "x", updated_at: "2026-01-02T03:04:05Z" });
    act(() => root.render(view([call, ev(2, "tool_result", { tool_call_id: "s", name: "scratchpad", status: "success", content: "Scratchpad replaced (1 characters)." })])));
    await settle();
    expect(Api.getBotScratchpad).toHaveBeenCalledTimes(2);
    expect(padButton(container)).not.toBeNull();
    act(() => root.unmount());
    container.remove();
  });
});
