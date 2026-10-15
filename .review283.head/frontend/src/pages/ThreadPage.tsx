import { useSaveMutation } from "../lib/saveNotifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Api, type AttachmentIn } from "../api/client";
import type { ThreadDetail } from "../api/types";
import { isBackendUnavailable } from "../api/errors";
import { useBusEvents } from "../api/sse";
import Composer from "../components/Composer";
import MessageList from "../components/MessageList";
import ThreadOdometer from "../components/ThreadOdometer";
import { Button, ErrorText, IconButton, OfflineNotice, Spinner } from "../components/ui";
import { ArrowLeftIcon, ArrowRightIcon, ChevronLeftIcon, MoreIcon } from "../components/icons";
import { isNearBottom, scrollToBottom } from "../lib/autoScroll";
import { emptyThreadState, hydrate, mergeRun, missedRunEnds, openRunIds, reduceThreadEvent, type ThreadState } from "../lib/threadState";
import { setOpenBotTitle } from "../lib/documentTitle";

export default function ThreadPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  // refetchOnMount "always": a re-entry (another thread window and back) must not be served
  // from a cache hit younger than staleTime. The per-thread SSE subscription is closed while
  // the page is unmounted and events are never replayed, so messages that arrived in between
  // are otherwise invisible until an unrelated refetch — only post-return events would show.
  const detail = useQuery({ queryKey: ["thread", id], queryFn: () => Api.getThread(id), refetchOnMount: "always", refetchInterval: 10_000 });
  const bots = useQuery({ queryKey: ["bots"], queryFn: Api.listBots, refetchInterval: 10_000 });
  const usage = useQuery({ queryKey: ["thread-usage", id], queryFn: () => Api.getThreadUsage(id) });
  // Keep the live per-thread transcript in the query cache so unmounting while navigating does
  // not discard tool calls and streaming output that arrived over SSE. The thread detail query
  // only contains persisted messages/open runs, not the in-progress run event transcript.
  const [state, setState] = useState<ThreadState>(() => qc.getQueryData<ThreadState>(["thread-state", id]) ?? emptyThreadState(id));
  const [notice, setNotice] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuThreadId, setMenuThreadId] = useState(id);
  const menuVisible = menuOpen && menuThreadId === id;
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setMenuOpen(false);
    setMenuThreadId(id);
  }, [id]);
  useLayoutEffect(() => {
    if (!menuVisible) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setMenuOpen(false); menuButtonRef.current?.focus(); }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    document.querySelector<HTMLElement>("#thread-actions-menu select, #thread-actions-menu button")?.focus();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [menuVisible, menuThreadId, id]);
  const scrollContainer = useRef<HTMLDivElement>(null);
  const shouldStickToBottom = useRef(true);
  const updateScrollStickiness = useCallback(() => {
    const el = scrollContainer.current;
    if (el) shouldStickToBottom.current = isNearBottom(el);
  }, []);
  // Switching threads reuses this component, so the transcript is reset while rendering the new
  // id rather than in an effect: an effect would first commit the previous thread's state.
  const [stateId, setStateId] = useState(id);
  const [hydratedFrom, setHydratedFrom] = useState<ThreadDetail>();
  if (stateId !== id) {
    setStateId(id);
    setState(qc.getQueryData<ThreadState>(["thread-state", id]) ?? emptyThreadState(id));
    setHasMore(false);
    setHydratedFrom(undefined);
  }
  useEffect(() => { shouldStickToBottom.current = true; }, [id]);
  useEffect(() => {
    // Never overwrite a thread's snapshot with state that belongs to another thread.
    if (state.threadId === id) qc.setQueryData(["thread-state", id], state);
  }, [id, qc, state]);
  // Navigating from one thread window straight to another reuses this component instance, so the
  // query observer just swaps keys — that is not a mount and refetchOnMount does not fire. The
  // previous thread's cached snapshot would be re-rendered as-is, hiding everything that arrived
  // since it was fetched (the closed per-thread SSE socket never replays missed events). Mark the
  // new thread's query stale on every actual id change so the open always refetches.
  const prevId = useRef(id);
  useEffect(() => {
    if (prevId.current === id) return;
    prevId.current = id;
    qc.invalidateQueries({ queryKey: ["thread", id] });
  }, [id, qc]);
  // Merge every new thread response into the transcript, also while rendering. Right after a
  // thread switch this waits one pass until the reset above has landed.
  const fetched = detail.data;
  if (fetched && fetched !== hydratedFrom && stateId === id) {
    setHydratedFrom(fetched);
    setState((s) => hydrate(s, fetched));
    setHasMore(fetched.has_more);
  }
  // A run this page still shows as open but the latest response no longer lists has finished
  // unseen; fetch its final state once per response, or its card would stay "running" for good.
  const checkedRuns = useRef<{ from?: ThreadDetail; ids: Set<string> }>({ ids: new Set() });
  useEffect(() => {
    if (!fetched || fetched !== hydratedFrom || fetched.id !== id) return;
    if (checkedRuns.current.from !== fetched) checkedRuns.current = { from: fetched, ids: new Set() };
    for (const runId of missedRunEnds(state, fetched)) {
      if (checkedRuns.current.ids.has(runId)) continue;
      checkedRuns.current.ids.add(runId);
      Api.getRun(runId)
        .then(({ events: _events, ...run }) => setState((s) =>
          s.threadId === run.thread_id ? reduceThreadEvent(s, { event: "run.updated", thread_id: run.thread_id, data: run }) : s))
        .catch(() => {});
    }
  }, [fetched, hydratedFrom, id, state]);
  // Ack on open and whenever new messages land, so the inbox badge stays honest.
  useEffect(() => { Api.ackThread(id).then(() => qc.invalidateQueries({ queryKey: ["inbox"] })).catch(() => {}); }, [id, qc, state.messages.length]);
  // Events published while the SSE socket was down are not replayed, so a reconnect leaves the
  // locally-reduced thread state behind. Refetch the thread instead of trusting it.
  useBusEvents(id, (e) => {
    setState((s) => reduceThreadEvent(s, e));
    // Usage is persisted incrementally, including while a run remains running.
    if (e.event === "run.updated") qc.invalidateQueries({ queryKey: ["thread-usage", id] });
  }, () => {
    qc.invalidateQueries({ queryKey: ["thread", id] });
    qc.invalidateQueries({ queryKey: ["thread-usage", id] });
  });
  const send = useMutation({
    mutationFn: ({ content, attachments }: { content: string; attachments: AttachmentIn[] }) => Api.postMessage(id, { content, attachments: attachments.length ? attachments : undefined }),
    onSuccess: (r) => setNotice(r.unaddressed ? "No bot was addressed. Mention a bot with @handle or set a default bot to wake one up." : null),
  });
  const loadOlder = useMutation({
    mutationFn: () => Api.getThread(id, state.messages[0].id),
    onSuccess: (older) => { setState((s) => hydrate(s, older)); setHasMore(older.has_more); },
  });
  const del = useMutation({ mutationFn: () => Api.deleteThread(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["threads"] }); nav("/threads"); } });
  const updateDefault = useSaveMutation({
    mutationFn: (default_bot_handle: string) => Api.updateThread(id, { default_bot_handle }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["thread", id] });
      qc.invalidateQueries({ queryKey: ["threads"] });
    },
  }, "Default bot saved");
  // Esc stops every open run in the thread, unless an open menu, list or dialog takes the key.
  const openRuns = openRunIds(state).join(" ");
  const stopping = useRef(new Set<string>());
  useEffect(() => {
    if (!openRuns) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
      if (document.querySelector('[role="menu"], [role="listbox"], [role="dialog"]')) return;
      for (const runId of openRuns.split(" ")) {
        if (stopping.current.has(runId)) continue;
        stopping.current.add(runId);
        Api.cancelRun(runId).catch(() => stopping.current.delete(runId));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openRuns]);
  const latestMessageId = state.messages.at(-1)?.id;
  const streamedChars = Object.values(state.streaming).reduce((a, s) => a + s.length, 0);
  const runEventCount = Object.values(state.runEvents).reduce((a, events) => a + events.length, 0);
  const runStatuses = Object.values(state.runs).map((r) => `${r.id}:${r.status}`).join("|");
  useLayoutEffect(() => {
    const el = scrollContainer.current;
    if (el && shouldStickToBottom.current) scrollToBottom(el);
  }, [id, latestMessageId, streamedChars, runEventCount, runStatuses]);

  // Build actor_id → bot icon key lookup
  const iconByActor = useMemo(() => {
    const map: Record<string, string> = {};
    for (const bot of bots.data ?? []) {
      map[bot.id] = bot.icon;
    }
    return map;
  }, [bots.data]);

  // Build actor_id → bot name lookup (bots that may not be thread participants yet)
  const nameByActor = useMemo(() => {
    const map: Record<string, string> = {};
    for (const bot of bots.data ?? []) {
      map[bot.id] = bot.name;
    }
    return map;
  }, [bots.data]);

  useEffect(() => {
    const title = state.title ?? detail.data?.title;
    if (title) setOpenBotTitle(title);
  }, [state.title, detail.data?.title]);

  if (detail.isLoading) return <Spinner />;
  if (!detail.data) {
    if (isBackendUnavailable(detail.error)) return <OfflineNotice />;
    return <ErrorText error={detail.error} />;
  }
  const t = detail.data;
  const displayedTitle = state.title ?? t.title;
  const usageData = usage.data;
  const costFormatter = (value: number) => value.toFixed(4);
  const handles = [...new Set([
    ...t.participants.filter((p) => p.kind === "bot").map((p) => p.handle),
    ...(bots.data ?? []).filter((b) => b.enabled).map((b) => b.handle),
  ])];
  const defaultSelect = (className: string, autoFocus = false) => (
    <select autoFocus={autoFocus} aria-label="Default bot" className={`rounded-ui border border-line bg-surface text-xs text-fg outline-none focus:border-accent ${className}`} value={t.default_bot_handle ?? ""} onChange={(e) => updateDefault.mutate(e.target.value)} disabled={updateDefault.isPending}>
      {handles.map((h) => <option key={h} value={h}>@{h}</option>)}
    </select>
  );
  return (
    <div className="mx-auto flex h-[calc(100vh-2rem)] max-w-4xl flex-col md:h-[calc(100vh-3rem)]">
      <header className="thread-header sticky top-0 z-10 border-b border-line bg-canvas">
        <div className="thread-header-main flex min-w-0 items-start gap-2">
          <Link to="/threads" aria-label="Back to threads" title="Back to threads" className="thread-header-back inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-ui border border-transparent text-muted hover:border-line hover:bg-sunken hover:text-fg">
            <ChevronLeftIcon className="h-4 w-4" />
          </Link>
          <div className="min-w-0 flex-1 pt-0.5">
            <p className="thread-header-kicker">Active thread</p>
            <h1 className="thread-header-title text-[16px] font-semibold tracking-[-0.01em]" aria-label={displayedTitle || "Untitled thread"} title={displayedTitle || "Untitled thread"}>{displayedTitle || "Untitled thread"}</h1>
            <div className="thread-header-context flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] leading-4 text-muted">
              <span className="min-w-0 break-words">{t.participants.map((p) => `@${p.handle}`).join(" ") || "No participants yet"}</span>
              <span className="min-w-0 break-words"><span className="text-faint">cwd </span>{t.working_directory ?? "."}</span>
            </div>
          </div>
          <div className="thread-header-controls flex shrink-0 items-center gap-1.5">
            <label className="hidden items-center gap-1.5 text-[11px] text-muted sm:flex">default
              {defaultSelect("h-8 px-1.5")}
            </label>
            <div className="relative" ref={menuRef}>
              <IconButton ref={menuButtonRef} aria-label="Thread actions" aria-controls="thread-actions-menu" aria-expanded={menuVisible} aria-haspopup="menu" onClick={() => { setMenuThreadId(id); setMenuOpen((open) => !open); }}>
                <MoreIcon className="h-4 w-4" />
              </IconButton>
              {menuVisible && <div id="thread-actions-menu" role="menu" className="absolute right-0 top-10 z-20 min-w-48 rounded-ui border border-line bg-surface p-1 shadow-[0_12px_32px_-12px_rgb(0_0_0/0.45)]">
                <div role="group" className="flex items-center justify-between gap-3 px-3 py-2 text-[13px] sm:hidden">Default bot
                  {defaultSelect("h-8 max-w-32 px-1.5", true)}
                </div>
                <button type="button" role="menuitem" disabled={del.isPending} onClick={() => { setMenuOpen(false); if (window.confirm("Delete thread?")) del.mutate(); }} className="h-9 w-full rounded-ui px-3 text-left text-[13px] text-danger hover:bg-danger/10">Delete thread</button>
              </div>}
            </div>
          </div>
        </div>
        <div className="thread-header-footer">
          <span className="thread-header-metrics-label">Usage</span>
          <span className="thread-header-counters" role="group" aria-label="Thread usage">
            <ThreadOdometer label="calls" value={usageData?.model_calls} loading={usage.isLoading} />
            <ThreadOdometer label="tokens in" indicator={<ArrowRightIcon className="h-3 w-3" />} indicatorLabel="Tokens in" value={usageData?.prompt_tokens} unit="tok" loading={usage.isLoading} />
            <ThreadOdometer label="tokens out" indicator={<ArrowLeftIcon className="h-3 w-3" />} indicatorLabel="Tokens out" value={usageData?.completion_tokens} unit="tok" loading={usage.isLoading} />
            <ThreadOdometer label="cost" value={usageData?.cost_usd} prefix="$" format={costFormatter} loading={usage.isLoading} />
          </span>
        </div>
      </header>
      {/* The thinking placeholder is rendered inline in MessageList, not as a separate banner. */}
      <div ref={scrollContainer} onScroll={updateScrollStickiness} className="scrollbar-subtle flex-1 overflow-y-auto py-5">
        {hasMore && state.messages.length > 0 && (
          <div className="mb-4 space-y-1 text-center">
            <Button variant="secondary" size="sm" onClick={() => loadOlder.mutate()} disabled={loadOlder.isPending}>Load older messages</Button>
            <ErrorText error={loadOlder.error} />
          </div>
        )}
        <MessageList state={state} participants={t.participants} onRunLoaded={(run) => setState((s) => mergeRun(s, run))} iconByActor={iconByActor} nameByActor={nameByActor} />
      </div>
      <div className="border-t border-line pt-3">
        {notice && <p className="mb-1.5 text-xs text-warn">{notice}</p>}
        <ErrorText error={send.error} />
        <Composer key={id} threadId={id} handles={handles} running={!!openRuns} autoFocus={detail.data.messages.length === 0} onSend={async (text, attachments) => { await send.mutateAsync({ content: text, attachments }); }} />      </div>
    </div>
  );
}
