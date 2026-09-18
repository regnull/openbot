import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Api, type AttachmentIn } from "../api/client";
import { isBackendUnavailable } from "../api/errors";
import { useBusEvents } from "../api/sse";
import Composer from "../components/Composer";
import WaitingIndicator from "../components/WaitingIndicator";
import MessageList from "../components/MessageList";
import { Button, ErrorText, OfflineNotice, Spinner } from "../components/ui";
import { isNearBottom, scrollToBottom } from "../lib/autoScroll";
import { emptyThreadState, hydrate, mergeRun, reduceThreadEvent, type ThreadState } from "../lib/threadState";
import { threadUsageLabel } from "../lib/threadUsage";

export default function ThreadPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  // refetchOnMount "always": a re-entry (another thread window and back) must not be served
  // from a cache hit younger than staleTime. The per-thread SSE subscription is closed while
  // the page is unmounted and events are never replayed, so messages that arrived in between
  // are otherwise invisible until an unrelated refetch — only post-return events would show.
  const detail = useQuery({ queryKey: ["thread", id], queryFn: () => Api.getThread(id), refetchOnMount: "always" });
  const bots = useQuery({ queryKey: ["bots"], queryFn: Api.listBots });
  const usage = useQuery({ queryKey: ["thread-usage", id], queryFn: () => Api.getThreadUsage(id) });
  const [state, setState] = useState<ThreadState>(emptyThreadState(id));
  const [notice, setNotice] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setMenuOpen(false); menuButtonRef.current?.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);
  const scrollContainer = useRef<HTMLDivElement>(null);
  const shouldStickToBottom = useRef(true);
  const updateScrollStickiness = useCallback(() => {
    const el = scrollContainer.current;
    if (el) shouldStickToBottom.current = isNearBottom(el);
  }, []);
  useEffect(() => { setState(emptyThreadState(id)); setHasMore(false); shouldStickToBottom.current = true; }, [id]);
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
  useEffect(() => { if (detail.data) { setState((s) => hydrate(s, detail.data)); setHasMore(detail.data.has_more); } }, [id, detail.data]);
  // Ack on open and whenever new messages land, so the inbox badge stays honest.
  useEffect(() => { Api.ackThread(id).then(() => qc.invalidateQueries({ queryKey: ["inbox"] })).catch(() => {}); }, [id, qc, state.messages.length]);
  // Events published while the SSE socket was down are not replayed, so a reconnect leaves the
  // locally-reduced thread state behind. Refetch the thread instead of trusting it.
  useBusEvents(id, (e) => {
    setState((s) => reduceThreadEvent(s, e));
    // Usage is written when a run leaves `running`, so that is when the header totals move.
    if (e.event === "run.updated" && e.data.status !== "running") qc.invalidateQueries({ queryKey: ["thread-usage", id] });
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
  const updateDefault = useMutation({
    mutationFn: (default_bot_handle: string) => Api.updateThread(id, { default_bot_handle }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["thread", id] });
      qc.invalidateQueries({ queryKey: ["threads"] });
    },
  });
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

  if (detail.isLoading) return <Spinner />;
  if (!detail.data) {
    if (isBackendUnavailable(detail.error)) return <OfflineNotice />;
    return <ErrorText error={detail.error} />;
  }
  const t = detail.data;
  const displayedTitle = state.title ?? t.title;
  const usageLine = usage.data ? threadUsageLabel(usage.data) : null;
  const handles = [...new Set([
    ...t.participants.filter((p) => p.kind === "bot").map((p) => p.handle),
    ...(bots.data ?? []).filter((b) => b.enabled).map((b) => b.handle),
  ])];
  return (
    <div className="mx-auto flex h-[calc(100vh-3rem)] max-w-4xl flex-col">
      <header className="thread-header sticky top-0 z-10 flex min-h-14 items-center gap-3 border-b border-zinc-200 bg-white/95 px-1 py-2 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
        <Link to="/threads" className="shrink-0 rounded-md px-2 py-2 text-sm text-zinc-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700">← <span className="hidden sm:inline">Threads</span></Link>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold">{displayedTitle || "Untitled thread"}</h1>
          <p className="truncate text-xs text-zinc-500">{t.participants.map((p) => `@${p.handle}`).join(" ")} · cwd {t.working_directory ?? "."}{usageLine ? ` · ${usageLine}` : ""}</p>
        </div>
        <label className="hidden shrink-0 items-center gap-2 text-xs text-zinc-500 sm:flex">Default
          <select aria-label="Default bot" className="h-10 rounded-md border border-zinc-300 bg-white px-2 dark:border-zinc-700 dark:bg-zinc-950" value={t.default_bot_handle ?? ""} onChange={(e) => updateDefault.mutate(e.target.value)} disabled={updateDefault.isPending}>
            {handles.map((h) => <option key={h} value={h}>@{h}</option>)}
          </select>
        </label>
        <div className="relative" ref={menuRef}>
          <button ref={menuButtonRef} type="button" aria-label="Thread actions" aria-expanded={menuOpen} aria-haspopup="menu" onClick={() => setMenuOpen((open) => !open)} className="h-11 w-11 rounded-md text-lg text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 hover:bg-zinc-100 dark:hover:bg-zinc-800">⋯</button>
          {menuOpen && <div role="menu" className="absolute right-0 top-12 z-20 min-w-48 rounded-md border border-zinc-200 bg-white p-1 shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
            <label className="flex items-center justify-between gap-3 px-3 py-2 text-sm sm:hidden">Default
              <select aria-label="Default bot" className="h-10 max-w-32 rounded-md border border-zinc-300 bg-white px-2 dark:border-zinc-700 dark:bg-zinc-950" value={t.default_bot_handle ?? ""} onChange={(e) => updateDefault.mutate(e.target.value)} disabled={updateDefault.isPending}>{handles.map((h) => <option key={h} value={h}>@{h}</option>)}</select>
            </label>
            <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); if (window.confirm("Delete thread?")) del.mutate(); }} className="h-11 w-full rounded px-3 text-left text-sm text-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-700 hover:bg-zinc-100 dark:hover:bg-zinc-800">Delete thread</button>
          </div>}
        </div>
      </header>
      {/* Above the scroll area on purpose: in a long thread a banner inside it would scroll out
          of view, and the whole point is a waiting state the reader cannot miss. */}
      <WaitingIndicator waiters={state.waiters} />
      <div ref={scrollContainer} onScroll={updateScrollStickiness} className="scrollbar-subtle flex-1 overflow-y-auto py-4">
        {hasMore && state.messages.length > 0 && (
          <div className="mb-3 space-y-1 text-center">
            <Button variant="secondary" onClick={() => loadOlder.mutate()} disabled={loadOlder.isPending}>Load older</Button>
            <ErrorText error={loadOlder.error} />
          </div>
        )}
        <MessageList state={state} participants={t.participants} onRunLoaded={(run) => setState((s) => mergeRun(s, run))} iconByActor={iconByActor} nameByActor={nameByActor} />
      </div>
      <div className="border-t border-zinc-200 pt-3 dark:border-zinc-800">
        {notice && <p className="mb-1 text-xs text-amber-600">{notice}</p>}
        <ErrorText error={send.error} />
        <Composer handles={handles} onSend={async (text, attachments) => { await send.mutateAsync({ content: text, attachments }); }} />
      </div>
    </div>
  );
}