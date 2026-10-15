import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { setOpenBotTitle } from "../lib/documentTitle";

const PAGE_TITLES: Record<string, string> = {
  "/inbox": "Inbox",
  "/threads": "Threads",
  "/bots": "Bots",
  "/bots/new": "New bot",
  "/settings": "Settings",
  "/scheduled": "Scheduled",
};

function pageTitleFor(pathname: string): string | undefined {
  if (PAGE_TITLES[pathname]) return PAGE_TITLES[pathname];
  if (pathname.startsWith("/bots/") && pathname !== "/bots/new") return "Bot";
  if (pathname.startsWith("/threads/") && pathname !== "/threads") return "Thread";
  return undefined;
}

/** Sets document.title from the current route. ThreadPage may refine it with the thread name. */
export default function DocumentTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    setOpenBotTitle(pageTitleFor(pathname));
  }, [pathname]);
  return null;
}
