import { useEffect, useState, useSyncExternalStore } from "react";
import { dismissSaveNotification, getSaveNotification, subscribe } from "../lib/saveNotifications";

export default function SaveNotification() {
  const notice = useSyncExternalStore(subscribe, getSaveNotification, () => null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!notice || hovered || focused) return;
    const timer = window.setTimeout(dismissSaveNotification, 5000);
    return () => window.clearTimeout(timer);
  }, [notice, hovered, focused]);
  return (
    <div className="pointer-events-none fixed inset-x-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-[100] flex justify-center">
      <div role="status" aria-live="polite" aria-atomic="true" className="max-w-sm">
        {notice && <div className={`pointer-events-auto flex items-center gap-3 rounded-lg border px-4 py-2 text-sm shadow-lg ${notice.tone === "success"
          ? "border-emerald-300 bg-white text-emerald-800 dark:border-emerald-700 dark:bg-zinc-900 dark:text-emerald-200"
          : "border-red-300 bg-white text-red-800 dark:border-red-700 dark:bg-zinc-900 dark:text-red-200"}`}
          onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}>
          <span className="min-w-0 break-words">{notice.message}</span>
          <button type="button" aria-label="Dismiss notification" className="-mr-2 flex size-11 shrink-0 items-center justify-center rounded-md focus-visible:outline-2 focus-visible:outline-offset-2"
            onClick={() => { setHovered(false); setFocused(false); dismissSaveNotification(); }}>✕</button>
        </div>}
      </div>
    </div>
  );
}
