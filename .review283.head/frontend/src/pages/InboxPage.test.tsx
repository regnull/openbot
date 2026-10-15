// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import InboxPage from "./InboxPage";
import type { InboxItem, Message, RunDetail, Thread } from "../api/types";

const fake = vi.hoisted(() => ({ api: {} as Record<string, (...args: never[]) => unknown> }));
vi.mock("../api/client", () => ({ Api: fake.api }));

const message = (id: string, threadId: string, content: string): InboxItem => ({
  id, actor_id: "me", thread_id: threadId, kind: "message", message_id: `m-${id}`, run_id: null, payload: {}, status: "queued",
  attempts: 0, last_error: null, created_at: "2026-09-26T10:00:00Z", processed_at: null,
  message: { id: `m-${id}`, thread_id: threadId, sender_actor_id: "b1", sender_kind: "bot", sender_name: "eng", content, mentions: [],
    hop: 0, run_id: null, metadata: {}, created_at: "2026-09-26T10:00:00Z" } satisfies Message,
});
const question: InboxItem = {
  id: "q1", actor_id: "me", thread_id: "t1", kind: "question", message_id: null, run_id: "r1", payload: {}, status: "queued",
  attempts: 0, last_error: null, created_at: "2026-09-26T10:00:00Z", processed_at: null, message: null,
};
const run: RunDetail = {
  id: "r1", actor_id: "b1", thread_id: "t1", status: "waiting_human", interrupt: { kind: "question", question: "Ship it?" },
  error: null, langsmith_run_id: null, created_at: "", started_at: null, finished_at: null, events: [],
};
const thread = (id: string, title: string): Thread => ({
  id, title, kind: "chat", created_by_actor_id: null, default_bot_actor_id: null, default_bot_handle: null, working_directory: null,
  external_ref: null, created_at: "", updated_at: "", last_message_at: null, participants: [],
});

describe("InboxPage", () => {
  let root: Root;
  let el: HTMLDivElement;
  let items: InboxItem[];
  let acked: string[];
  let releaseAcks: () => void;
  const text = (): string => el.textContent ?? "";
  const until = async (cond: () => boolean, what: string): Promise<void> => {
    const deadline = Date.now() + 2_000;
    while (!cond()) {
      if (Date.now() > deadline) throw new Error(`timeout waiting for ${what}; page text: ${text().slice(0, 300)}`);
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    }
  };
  const button = (label: string): HTMLButtonElement => {
    const b = Array.from(el.querySelectorAll("button")).find((x) => x.textContent === label);
    if (!b) throw new Error(`no ${label} button`);
    return b;
  };
  const render = async (): Promise<void> => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await act(async () => {
      root.render(
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={["/inbox"]}><InboxPage /></MemoryRouter>
        </QueryClientProvider>,
      );
    });
  };

  beforeEach(() => {
    items = [];
    acked = [];
    const gate = new Promise<void>((resolve) => { releaseAcks = resolve; });
    fake.api.listInbox = () => Promise.resolve(items) as never;
    fake.api.listBots = () => Promise.resolve([]) as never;
    fake.api.listThreads = () => Promise.resolve([thread("t1", "Release planning"), thread("t2", "Bug triage")]) as never;
    fake.api.getRun = () => Promise.resolve(run) as never;
    fake.api.ackItem = (id: string) => { acked.push(id); return gate.then(() => ({})) as never; };
    el = document.createElement("div");
    document.body.appendChild(el);
    root = createRoot(el);
  });

  afterEach(() => {
    act(() => root.unmount());
    el.remove();
  });

  it("says all caught up only when nothing is waiting", async () => {
    await render();
    await until(() => text().includes("All caught up"), "empty inbox");
  });

  it("does not claim all caught up while a question is waiting", async () => {
    items = [question];
    await render();
    await until(() => text().includes("Ship it?"), "question card");
    expect(text()).toContain("No unread messages.");
    expect(text()).not.toContain("All caught up");
  });

  it("names the thread of each unread group", async () => {
    items = [message("a", "t1", "hello"), message("b", "t1", "again"), message("c", "t2", "found it")];
    await render();
    await until(() => text().includes("Release planning · 2 new messages"), "thread title");
    expect(text()).toContain("Bug triage · 1 new message");
  });

  it("marks everything read once, and blocks repeat clicks while acking", async () => {
    items = [message("a", "t1", "hello"), message("b", "t2", "found it")];
    await render();
    await until(() => text().includes("Mark all read"), "mark all read");
    await act(async () => { button("Mark all read").click(); });
    await until(() => button("Mark all read").disabled, "pending state");
    expect(button("Mark read").disabled).toBe(true);
    await act(async () => { button("Mark all read").click(); });
    expect(acked).toEqual(["a", "b"]);
    await act(async () => { releaseAcks(); });
    await until(() => !button("Mark all read").disabled, "acks settle");
  });

  it("hides mark all read for a single thread", async () => {
    items = [message("a", "t1", "hello")];
    await render();
    await until(() => text().includes("Release planning"), "thread title");
    expect(text()).not.toContain("Mark all read");
  });
});
