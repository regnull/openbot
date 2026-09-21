import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Api } from "../api/client";
import { useBusEvents } from "../api/sse";
import { shouldRefreshBots } from "../lib/botActivity";
import { isThreadActive, recentThreads, threadLabel } from "../lib/recentThreads";
import BotActivityIndicator from "./BotActivityIndicator";
import BotIcon from "./BotIcon";
import ThemeToggle from "./ThemeToggle";
import { BotsIcon, InboxIcon, PanelLeftCloseIcon, PanelLeftOpenIcon, PlusIcon, SettingsIcon, ThreadsIcon } from "./icons";

// ── Local-storage helpers ─────────────────────────────────────────────────────
const LS_WIDTH = "openbot:sidebar-width";
const LS_COLLAPSED = "openbot:sidebar-collapsed";

const MIN_WIDTH = 180;
const MAX_WIDTH = 360;
const COLLAPSED_WIDTH = 52;

function readStoredWidth(): number {
  try {
    const v = Number(localStorage.getItem(LS_WIDTH));
    return Number.isFinite(v) && v >= MIN_WIDTH && v <= MAX_WIDTH ? v : 232;
  } catch { return 232; }
}

function readStoredCollapsed(): boolean {
  try { return localStorage.getItem(LS_COLLAPSED) === "1"; } catch { return false; }
}

/** Below this width the sidebar is an icon rail and the full list opens as a drawer over the page. */
const NARROW = "(max-width: 767px)";
function useNarrow(): boolean {
  return useSyncExternalStore(
    (cb) => { const mq = window.matchMedia(NARROW); mq.addEventListener("change", cb); return () => mq.removeEventListener("change", cb); },
    () => window.matchMedia(NARROW).matches,
    () => false,
  );
}

// ── Style helpers ─────────────────────────────────────────────────────────────
/**
 * Keep the row at 36px to match the collapsed rail controls. The 20px line
 * box is intentional: the 13px labels need room for font descenders (notably
 * `g`, `p`, `q`, and `y`) while the flex row keeps that box vertically centered.
 * The label wrappers also inherit this line-height, so `truncate` does not
 * clip glyphs inside its overflow-hidden box.
 */
/** Nav rows: the active one is marked by a short accent bar in the gutter, not by a filled pill. */
const row = ({ isActive }: { isActive: boolean }) =>
  `relative flex h-9 items-center gap-2.5 rounded-ui px-2 text-[13px] leading-5 transition-colors ${
    isActive
      ? "bg-sunken font-medium text-fg before:absolute before:bottom-1.5 before:left-0 before:top-1.5 before:w-0.5 before:rounded-full before:bg-accent"
      : "text-muted hover:bg-sunken/60 hover:text-fg"}`;
const iconRow = ({ isActive }: { isActive: boolean }) =>
  `relative flex h-9 w-9 items-center justify-center rounded-ui transition-colors ${
    isActive
      ? "bg-sunken text-fg before:absolute before:bottom-2 before:left-0 before:top-2 before:w-0.5 before:rounded-full before:bg-accent"
      : "text-muted hover:bg-sunken/60 hover:text-fg"}`;
const SectionLabel = ({ children }: { children: string }) => <div className="mb-1 px-2 text-[11px] leading-4 text-faint">{children}</div>;

const NAV = [
  { to: "/inbox", label: "Inbox", Icon: InboxIcon, end: false },
  { to: "/threads", label: "Threads", Icon: ThreadsIcon, end: true },
  { to: "/bots", label: "Bots", Icon: BotsIcon, end: true },
  { to: "/settings", label: "Settings", Icon: SettingsIcon, end: false },
] as const;

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
  const [storedCollapsed, setCollapsed] = useState(readStoredCollapsed);
  const dragging = useRef(false);
  // On a phone the sidebar is always a rail; "expand" opens it as a drawer. The drawer remembers the
  // path it was opened on, so any navigation closes it without an effect.
  const narrow = useNarrow();
  const { pathname } = useLocation();
  const [drawerPath, setDrawerPath] = useState<string | null>(null);
  const drawerOpen = drawerPath === pathname;
  const setDrawerOpen = (open: boolean) => setDrawerPath(open ? pathname : null);
  const collapsed = narrow ? !drawerOpen : storedCollapsed;
  const expand = () => (narrow ? setDrawerOpen(true) : setCollapsed(false));
  const collapse = () => (narrow ? setDrawerOpen(false) : setCollapsed(true));

  // Persist width (only when expanded).
  useEffect(() => {
    if (!storedCollapsed) {
      try { localStorage.setItem(LS_WIDTH, String(width)); } catch { /* noop */ }
    }
  }, [width, storedCollapsed]);

  // Persist collapsed state.
  useEffect(() => {
    try { localStorage.setItem(LS_COLLAPSED, storedCollapsed ? "1" : "0"); } catch { /* noop */ }
  }, [storedCollapsed]);

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

  const effectiveWidth = collapsed ? COLLAPSED_WIDTH : narrow ? Math.min(width, 280) : width;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* On a phone the open drawer floats over the page; a tap outside closes it. */}
      {narrow && drawerOpen && <div className="fixed inset-0 z-30 bg-overlay" onClick={() => setDrawerOpen(false)} aria-hidden />}
      {narrow && drawerOpen && <div className="shrink-0" style={{ width: COLLAPSED_WIDTH }} aria-hidden />}
      {/* ── Sidebar ──────────────────────────────────────────────────────────── */}
      <aside
        className={`flex h-full shrink-0 flex-col overflow-hidden border-r border-line bg-surface transition-[width] duration-200 ease-in-out ${narrow && drawerOpen ? "fixed inset-y-0 left-0 z-40 shadow-[0_0_60px_-10px_rgb(0_0_0/0.5)]" : ""}`}
        style={{ width: effectiveWidth }}
      >
        {/* ── Expanded content ───────────────────────────────────────────────── */}
        {!collapsed && (
          <>
            <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
              <img src="/logo-icon.svg" alt="" className="h-10 w-10 rounded-[8px]" aria-hidden="true" />
              <span className="text-base font-semibold tracking-tight">OpenBot</span>
            </div>
            <div className="scrollbar-subtle flex-1 overflow-y-auto px-2 py-3">
              <nav className="space-y-0.5" aria-label="Main">
                {NAV.map(({ to, label, Icon, end }) => (
                  <NavLink key={to} to={to} className={row} end={end}>
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">{label}</span>
                    {to === "/inbox" && unread > 0 && (
                      <span className="rounded-ui bg-accent px-1.5 text-[11px] font-medium leading-4 text-on-accent" aria-label={`${unread} unread`}>{unread}</span>
                    )}
                  </NavLink>
                ))}
              </nav>
              <div className="mt-3">
                <NavLink to="/threads" end className="flex h-9 items-center justify-center gap-1.5 rounded-ui border border-accent bg-accent px-3 text-[13px] font-medium leading-5 text-on-accent transition-colors hover:border-accent-strong hover:bg-accent-strong">
                  <PlusIcon className="h-3.5 w-3.5" />
                  New thread
                </NavLink>
              </div>
              <section className="mt-5" aria-label="Recent threads">
                <SectionLabel>recent threads</SectionLabel>
                <div className="space-y-0.5">
                  {recent.visible.map((t) => (
                    <NavLink key={t.id} to={`/threads/${t.id}`} className={row} title={threadLabel(t)}>
                      <span className="min-w-0 flex-1 truncate">{threadLabel(t)}</span>
                      <BotActivityIndicator active={isThreadActive(t)} />
                    </NavLink>
                  ))}
                  {threads.data?.length === 0 && <div className="px-2 text-xs text-faint">No threads yet</div>}
                  {recent.hasMore && (
                    <NavLink to="/threads" end className="block px-2 py-1.5 text-xs text-faint hover:text-muted">All threads</NavLink>
                  )}
                </div>
              </section>
              <section className="mt-5" aria-label="Bots">
                <SectionLabel>bots</SectionLabel>
                <div className="space-y-1">
                  {bots.data?.map((bot) => (
                    <NavLink key={bot.id} to={`/bots/${bot.id}`} className={row} title={bot.name}>
                      <BotIcon icon={bot.icon} className="h-7 w-7 text-base" />
                      <span className="min-w-0 flex-1 truncate">@{bot.handle}</span>
                      <BotActivityIndicator active={bot.active} />
                    </NavLink>
                  ))}
                  {bots.data?.length === 0 && <div className="px-2 text-xs text-faint">No bots yet</div>}
                </div>
              </section>
            </div>
            <div className="flex h-11 shrink-0 items-center justify-between border-t border-line px-2">
              <ThemeToggle />
              <button
                type="button"
                onClick={collapse}
                className="inline-flex h-8 w-8 items-center justify-center rounded-ui text-muted hover:bg-sunken hover:text-fg"
                aria-label="Collapse sidebar"
                title="Collapse sidebar"
              >
                <PanelLeftCloseIcon className="h-4 w-4" />
              </button>
            </div>
          </>
        )}

        {/* ── Collapsed icons ────────────────────────────────────────────────── */}
        {collapsed && (
          <>
            <div className="flex h-12 shrink-0 items-center justify-center border-b border-line">
              <img src="/logo-icon.svg" alt="OpenBot" className="h-10 w-10 rounded-[8px]" />
            </div>
            <nav className="flex flex-1 flex-col items-center gap-1 py-3" aria-label="Main">
              {NAV.map(({ to, label, Icon, end }) => (
                <NavLink key={to} to={to} className={iconRow} title={label} aria-label={label} end={end}>
                  <Icon className="h-4 w-4" />
                  {to === "/inbox" && unread > 0 && <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-accent" aria-label={`${unread} unread`} />}
                </NavLink>
              ))}
              <NavLink to="/threads" end className="mt-2 flex h-9 w-9 items-center justify-center rounded-ui border border-accent bg-accent text-on-accent hover:bg-accent-strong" title="New thread" aria-label="New thread">
                <PlusIcon className="h-4 w-4" />
              </NavLink>
            </nav>
            <div className="flex shrink-0 flex-col items-center gap-1 border-t border-line py-2">
              <ThemeToggle compact />
              <button
                type="button"
                onClick={expand}
                className="inline-flex h-8 w-8 items-center justify-center rounded-ui text-muted hover:bg-sunken hover:text-fg"
                aria-label="Expand sidebar"
                title="Expand sidebar"
              >
                <PanelLeftOpenIcon className="h-4 w-4" />
              </button>
            </div>
          </>
        )}
      </aside>

      {/* ── Resize handle ─────────────────────────────────────────────────────── */}
      {!collapsed && !narrow && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          className="relative z-10 -ml-px w-1 shrink-0 cursor-col-resize touch-none select-none transition-colors hover:bg-accent/50"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
      )}

      {/* ── Main content ──────────────────────────────────────────────────────── */}
      <main className="scrollbar-subtle min-w-0 flex-1 overflow-y-auto p-4 md:p-6">
        <Outlet />
      </main>
    </div>
  );
}
