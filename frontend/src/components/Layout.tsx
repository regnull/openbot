import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { Api } from "../api/client";
import { useBusEvents } from "../api/sse";

const link = ({ isActive }: { isActive: boolean }) =>
  `block rounded-md px-3 py-2 text-sm ${isActive ? "bg-zinc-200 font-medium dark:bg-zinc-800" : "hover:bg-zinc-100 dark:hover:bg-zinc-900"}`;

export default function Layout() {
  const qc = useQueryClient();
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: Api.listInbox });
  useBusEvents(null, (e) => {
    if (e.event === "inbox.updated") qc.invalidateQueries({ queryKey: ["inbox"] });
    if (e.event === "message.created") qc.invalidateQueries({ queryKey: ["threads"] });
  });
  const unread = inbox.data?.length ?? 0;
  return (
    <div className="flex min-h-screen">
      <aside className="w-52 shrink-0 border-r border-zinc-200 p-3 dark:border-zinc-800">
        <div className="mb-4 px-3 text-lg font-bold">OpenBot</div>
        <nav className="space-y-1">
          <NavLink to="/inbox" className={link}>Inbox {unread > 0 && <span className="ml-1 rounded-full bg-blue-600 px-2 text-xs text-white">{unread}</span>}</NavLink>
          <NavLink to="/threads" className={link}>Threads</NavLink>
          <NavLink to="/bots" className={link}>Bots</NavLink>
          <NavLink to="/settings" className={link}>Settings</NavLink>
        </nav>
      </aside>
      <main className="min-w-0 flex-1 p-6"><Outlet /></main>
    </div>
  );
}
