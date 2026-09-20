// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { describe, expect, it } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MessageList from "../components/MessageList";
import { emptyThreadState, reduceThreadEvent } from "../lib/threadState";
import type { Participant } from "../api/types";

const participants: Participant[] = [
  { actor_id: "b1", kind: "bot", handle: "eng", name: "Engineer" },
];

const mkRun = (id: string, status: string, actor_id = "b1") => ({
  id, actor_id, thread_id: "t", status, interrupt: null, error: null,
  langsmith_run_id: null, created_at: "2026-01-01T00:00:00Z", started_at: null, finished_at: null,
});

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
};

/** Render MessageList into a fresh container, return the container for assertions. */
const render = (s: ReturnType<typeof emptyThreadState>) => {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(wrap(
      <MessageList state={s} participants={participants} onRunLoaded={() => {}} nameByActor={{ b1: "Engineer" }} />,
    ));
  });
  return { container, root, cleanup: () => { act(() => root.unmount()); container.remove(); } };
};

describe("MessageList busy indicator", () => {
  it("shows BotBusyIndicator for a running run with no events or streaming", () => {
    let s = emptyThreadState("t");
    s = reduceThreadEvent(s, { event: "run.updated", thread_id: "t", data: mkRun("r1", "running") });
    const { container, cleanup } = render(s);
    try {
      expect(container.textContent).toContain("Engineer");
      expect(container.textContent).toContain("busy, waiting");
      expect(container.querySelector("[role='status']")).toBeTruthy();
      expect(container.querySelector(".bot-busy-dot")).toBeTruthy();
    } finally { cleanup(); }
  });

  it("shows BotBusyIndicator for a queued run", () => {
    let s = emptyThreadState("t");
    s = reduceThreadEvent(s, { event: "run.updated", thread_id: "t", data: mkRun("r1", "queued") });
    const { container, cleanup } = render(s);
    try {
      expect(container.textContent).toContain("busy, waiting");
      expect(container.querySelector("[role='status']")).toBeTruthy();
    } finally { cleanup(); }
  });

  it("switches to RunCard when tool_call events arrive", () => {
    let s = emptyThreadState("t");
    s = reduceThreadEvent(s, { event: "run.updated", thread_id: "t", data: mkRun("r1", "running") });
    s = reduceThreadEvent(s, {
      event: "run.event", thread_id: "t",
      data: { id: "e1", run_id: "r1", seq: 0, type: "tool_call", payload: { name: "shell", args: {} }, created_at: "" },
    });
    const { container, cleanup } = render(s);
    try {
      expect(container.querySelector("[role='status']")).toBeNull();
      expect(container.textContent).toContain("shell");
    } finally { cleanup(); }
  });

  it("switches to RunCard when streaming text arrives", () => {
    let s = emptyThreadState("t");
    s = reduceThreadEvent(s, { event: "run.updated", thread_id: "t", data: mkRun("r1", "running") });
    s = reduceThreadEvent(s, {
      event: "run.event", thread_id: "t",
      data: { run_id: "r1", type: "text_delta", payload: { delta: "Hello" } },
    });
    const { container, cleanup } = render(s);
    try {
      expect(container.querySelector("[role='status']")).toBeNull();
      expect(container.textContent).toContain("Hello");
    } finally { cleanup(); }
  });

  it("shows no placeholder when bot is idle (no active runs)", () => {
    const s = emptyThreadState("t");
    const { container, cleanup } = render(s);
    try {
      expect(container.querySelector("[role='status']")).toBeNull();
      expect(container.textContent).toContain("Start a focused conversation");
    } finally { cleanup(); }
  });

  it("shows RunCard for waiting_human status without events (not BotBusyIndicator)", () => {
    let s = emptyThreadState("t");
    s = reduceThreadEvent(s, { event: "run.updated", thread_id: "t", data: mkRun("r1", "waiting_human") });
    const { container, cleanup } = render(s);
    try {
      expect(container.textContent).toContain("Engineer");
      expect(container.textContent).toContain("waiting human");
    } finally { cleanup(); }
  });

  it("handles multiple concurrent active runs with indicators", () => {
    let s = emptyThreadState("t");
    s = reduceThreadEvent(s, { event: "run.updated", thread_id: "t", data: mkRun("r1", "running", "b1") });
    s = reduceThreadEvent(s, { event: "run.updated", thread_id: "t", data: mkRun("r2", "queued", "b1") });
    const { container, cleanup } = render(s);
    try {
      const indicators = container.querySelectorAll("[role='status']");
      expect(indicators).toHaveLength(2);
    } finally { cleanup(); }
  });
});
