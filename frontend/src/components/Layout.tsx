import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { Api } from "../api/client";
import { useBusEvents } from "../api/sse";
import { shouldRefreshBots } from "../lib/botActivity";
import { recentThreads, threadLabel } from "../lib/recentThreads";
import BotActivityIndicator from "./BotActivityIndicator";
import BotIcon from "./BotIcon";

const link = ({ isActive }: { isActive: boolean }) =>
  `block rounded-md px-3 py-2 text-sm ${isActive ? "bg-zinc-200 font-medium dark:bg-zinc-800" : "hover:bg-zinc-100 dark:hover:bg-zinc-900"}`;
const item = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${isActive ? "bg-zinc-200 font-medium dark:bg-zinc-800" : "hover:bg-zinc-100 dark:hover:bg-zinc-900"}`;

export default function Layout() {
  const qc = useQueryClient();
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: Api.listInbox });
  const bots = useQuery({ queryKey: ["bots"], queryFn: Api.listBots });
  const threads = useQuery({ queryKey: ["threads"], queryFn: Api.listThreads });
  useBusEvents(null, (e) => {
    if (e.event === "inbox.updated") qc.invalidateQueries({ queryKey: ["inbox"] });
    if (e.event === "message.created") qc.invalidateQueries({ queryKey: ["threads"] });
    if (shouldRefreshBots(e)) qc.invalidateQueries({ queryKey: ["bots"] });
  }, () => {
    // Missed events during the disconnect would leave a stale unread badge and thread list.
    qc.invalidateQueries({ queryKey: ["inbox"] });
    qc.invalidateQueries({ queryKey: ["threads"] });
    qc.invalidateQueries({ queryKey: ["bots"] });
  });
  const unread = inbox.data?.length ?? 0;
  const recent = recentThreads(threads.data);
  return (
    <div className="flex min-h-screen">
      <aside className="w-52 shrink-0 border-r border-zinc-200 p-3 dark:border-zinc-800">
        <div className="mb-4 px-3 text-lg font-bold">OpenBot</div>
        <nav className="space-y-1">
          <NavLink to="/inbox" className={link}>Inbox {unread > 0 && <span className="ml-1 rounded-full bg-blue-600 px-2 text-xs text-white">{unread}</span>}</NavLink>
          <NavLink to="/threads" className={link} end>Threads</NavLink>
          <NavLink to="/bots" className={link} end>Bots</NavLink>
          <NavLink to="/settings" className={link}>Settings</NavLink>
        </nav>
        <section className="mt-6" aria-label="Recent threads">
          <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">Recent threads</div>
          <div className="space-y-1">
            {recent.visible.map((t) => (
              <NavLink key={t.id} to={`/threads/${t.id}`} className={item} title={threadLabel(t)}>
                <span className="min-w-0 flex-1 truncate">{threadLabel(t)}</span>
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
                <BotIcon icon={bot.icon} className="h-6 w-6 text-sm" />
                <span className="min-w-0 flex-1 truncate">@{bot.handle}</span>
                <BotActivityIndicator active={bot.active} />
              </NavLink>
            ))}
            {bots.data?.length === 0 && <div className="px-3 text-xs text-zinc-500">No bots</div>}
          </div>
        </section>
      </aside>
      <main className="min-w-0 flex-1 p-6"><Outlet /></main>
    </div>
  );
}
