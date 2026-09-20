import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { Api } from "../api/client";
import { useBusEvents } from "../api/sse";
import { shouldRefreshBots } from "../lib/botActivity";
import { isThreadActive, recentThreads, threadLabel } from "../lib/recentThreads";
import BotActivityIndicator from "./BotActivityIndicator";
import BotIcon from "./BotIcon";

// ── Local-storage helpers ─────────────────────────────────────────────────────
const LS_WIDTH = "openbot:sidebar-width";
const LS_COLLAPSED = "openbot:sidebar-collapsed";

const MIN_WIDTH = 160;
const MAX_WIDTH = 360;
const COLLAPSED_WIDTH = 48;

function readStoredWidth(): number {
  try {
    const v = Number(localStorage.getItem(LS_WIDTH));
    return Number.isFinite(v) && v >= MIN_WIDTH && v <= MAX_WIDTH ? v : 208; // 208 = w-52
  } catch { return 208; }
}

function readStoredCollapsed(): boolean {
  try { return localStorage.getItem(LS_COLLAPSED) === "1"; } catch { return false; }
}

// ── Style helpers ─────────────────────────────────────────────────────────────
const link = ({ isActive }: { isActive: boolean }) =>
  `block rounded-md px-3 py-2 text-sm ${isActive ? "bg-zinc-200 font-medium dark:bg-zinc-800" : "hover:bg-zinc-100 dark:hover:bg-zinc-900"}`;
const linkIcon = ({ isActive }: { isActive: boolean }) =>
  `flex items-center justify-center rounded-md p-2 ${isActive ? "bg-zinc-200 font-medium dark:bg-zinc-800" : "hover:bg-zinc-100 dark:hover:bg-zinc-900"}`;
const item = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${isActive ? "bg-zinc-200 font-medium dark:bg-zinc-800" : "hover:bg-zinc-100 dark:hover:bg-zinc-900"}`;

// ── Component ─────────────────────────────────────────────────────────────────
export default function Layout() {
  const qc = useQueryClient();
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: Api.listInbox });
  const bots = useQuery({ queryKey: ["bots"], queryFn: Api.listBots });
  const threads = useQuery({ queryKey: ["threads"], queryFn: Api.listThreads });

  useBusEvents(null, (e) => {
    if (e.event === "inbox.updated") qc.invalidateQueries({ queryKey: ["inbox"] });
    if (e.event === "message.created" || e.event === "thread.updated") {
      qc.invalidateQueries({ queryKey: ["threads"] });
    }
    if (shouldRefreshBots(e)) qc.invalidateQueries({ queryKey: ["bots"] });
  }, () => {
    qc.invalidateQueries({ queryKey: ["inbox"] });
    qc.invalidateQueries({ queryKey: ["threads"] });
    qc.invalidateQueries({ queryKey: ["bots"] });
  });

  const unread = inbox.data?.length ?? 0;
  const recent = recentThreads(threads.data);

  // ── Sidebar width & collapse state ──────────────────────────────────────────
  const [width, setWidth] = useState(readStoredWidth);
  const [collapsed, setCollapsed] = useState(readStoredCollapsed);
  const dragging = useRef(false);

  // Persist width (only when expanded).
  useEffect(() => {
    if (!collapsed) {
      try { localStorage.setItem(LS_WIDTH, String(width)); } catch { /* noop */ }
    }
  }, [width, collapsed]);

  // Persist collapsed state.
  useEffect(() => {
    try { localStorage.setItem(LS_COLLAPSED, collapsed ? "1" : "0"); } catch { /* noop */ }
  }, [collapsed]);

  // ── Drag-resize logic ───────────────────────────────────────────────────────
  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    dragging.current = true;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return;
    const newW = Math.round(e.clientX);
    setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, newW)));
  }, []);

  const onPointerUp = useCallback(() => { dragging.current = false; }, []);

  const effectiveWidth = collapsed ? COLLAPSED_WIDTH : width;

  return (
    <div className="flex min-h-screen">
      {/* ── Sidebar ──────────────────────────────────────────────────────────── */}
      <aside
        className="group/sidebar shrink-0 overflow-hidden border-r border-zinc-200 p-3 transition-[width] duration-200 ease-in-out dark:border-zinc-800"
        style={{ width: effectiveWidth }}
      >
        {/* ── Expanded content ───────────────────────────────────────────────── */}
        {!collapsed && (
          <>
            <div className="mb-4 px-3 text-lg font-bold">OpenBot</div>
            <nav className="space-y-1">
              <NavLink to="/inbox" className={link}>
                Inbox{" "}
                {unread > 0 && (
                  <span className="ml-1 rounded-full bg-blue-600 px-2 text-xs text-white">{unread}</span>
                )}
              </NavLink>
              <NavLink to="/threads" className={link} end>Threads</NavLink>
              <NavLink to="/bots" className={link} end>Bots</NavLink>
              <NavLink to="/settings" className={link}>Settings</NavLink>
            </nav>
            <div className="mt-4 px-2">
              <NavLink to="/threads" end className="flex items-center justify-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                New Thread
              </NavLink>
            </div>
            <section className="mt-6" aria-label="Recent threads">
              <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">Recent threads</div>
              <div className="space-y-1">
                {recent.visible.map((t) => (
                  <NavLink key={t.id} to={`/threads/${t.id}`} className={item} title={threadLabel(t)}>
                    <span className="min-w-0 flex-1 truncate">{threadLabel(t)}</span>
                    <BotActivityIndicator active={isThreadActive(t)} />
                  </NavLink>
                ))}
                {threads.data?.length === 0 && <div className="px-3 text-xs text-zinc-500">No threads</div>}
                {recent.hasMore && (
                  <NavLink to="/threads" end className="block px-2 py-1.5 text-xs text-zinc-500 hover:underline">See more…</NavLink>
                )}
              </div>
            </section>
            <section className="mt-6" aria-label="Bots">
              <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">Bots</div>
              <div className="space-y-1">
                {bots.data?.map((bot) => (
                  <NavLink key={bot.id} to={`/bots/${bot.id}`} className={item}>
                    <BotIcon icon={bot.icon} className="h-8 w-8 text-base" />
                    <span className="min-w-0 flex-1 truncate">@{bot.handle}</span>
                    <BotActivityIndicator active={bot.active} />
                  </NavLink>
                ))}
                {bots.data?.length === 0 && <div className="px-3 text-xs text-zinc-500">No bots</div>}
              </div>
            </section>
          </>
        )}

        {/* ── Collapsed icons ────────────────────────────────────────────────── */}
        {collapsed && (
          <nav className="mt-1 space-y-1">
            <NavLink to="/inbox" className={`${linkIcon} relative`} title="Inbox">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" /><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
              </svg>
              {unread > 0 && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-blue-600" />}
            </NavLink>
            <NavLink to="/threads" className={linkIcon} title="Threads" end>
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </NavLink>
            <NavLink to="/bots" className={linkIcon} title="Bots" end>
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="9" cy="16" r="1" /><circle cx="15" cy="16" r="1" /><path d="M8 11V7a4 4 0 1 1 8 0v4" />
              </svg>
            </NavLink>
            <NavLink to="/settings" className={linkIcon} title="Settings">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
            </NavLink>
          </nav>
        )}
      </aside>

      {/* ── Resize handle ─────────────────────────────────────────────────────── */}
      <div className="relative z-10 flex w-1 shrink-0 select-none">
        {/* Collapse button — appears on hover near the top */}
        {!collapsed && (
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            className="absolute -right-3 top-3 z-20 flex h-6 w-6 items-center justify-center rounded-full border border-zinc-200 bg-white text-zinc-400 opacity-0 shadow-sm transition-opacity hover:text-zinc-600 group-hover/sidebar:opacity-100 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:text-zinc-300"
            aria-label="Collapse sidebar"
          >
            <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="11 17 6 12 11 7" /><polyline points="18 17 13 12 18 7" />
            </svg>
          </button>
        )}
        <div
          role="separator"
          aria-orientation="vertical"
          className="group/sidebar h-full w-full cursor-col-resize touch-none hover:bg-blue-500/30"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        >
          {/* Visual grip dots */}
          <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col gap-0.5 opacity-0 transition-opacity group-hover/sidebar:opacity-100">
            <span className="block h-0.5 w-0.5 rounded-full bg-zinc-400" />
            <span className="block h-0.5 w-0.5 rounded-full bg-zinc-400" />
            <span className="block h-0.5 w-0.5 rounded-full bg-zinc-400" />
          </span>
        </div>
      </div>

      {/* ── Main content ──────────────────────────────────────────────────────── */}
      <main className="min-w-0 flex-1 p-6">
        {/* Expand sidebar button — shown only when collapsed */}
        {collapsed && (
          <button
            type="button"
            onClick={() => setCollapsed(false)}
            className="mb-4 flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
            aria-label="Expand sidebar"
          >
            <svg className="h-3.5 w-3.5 rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="11 17 6 12 11 7" /><polyline points="18 17 13 12 18 7" />
            </svg>
            Show sidebar
          </button>
        )}
        <Outlet />
      </main>
    </div>
  );
}
