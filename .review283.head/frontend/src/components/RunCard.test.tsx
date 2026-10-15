// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { describe, expect, it } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RunCard from "./RunCard";
import type { Run, RunEvent } from "../api/types";

const run: Run = {
  id: "r", actor_id: "b1", thread_id: "t", status: "completed", interrupt: null, error: null,
  langsmith_run_id: null, created_at: "2026-01-01T00:00:00Z", started_at: null, finished_at: null,
};
const ev = (seq: number, type: string, payload: Record<string, unknown>): RunEvent =>
  ({ id: `e${seq}`, run_id: "r", seq, type, payload, created_at: "2026-01-01T00:00:00Z" });

const render = (events: RunEvent[]) => {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const qc = new QueryClient();
  act(() => root.render(<QueryClientProvider client={qc}><RunCard run={run} events={events} /></QueryClientProvider>));
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
