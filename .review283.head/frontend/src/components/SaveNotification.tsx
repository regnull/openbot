import { useEffect, useState, useSyncExternalStore } from "react";
import { dismissSaveNotification, getSaveNotification, subscribe } from "../lib/saveNotifications";
import { CloseIcon } from "./icons";

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
        {notice && <div className={`pointer-events-auto flex items-center gap-3 rounded-ui border-l-2 border border-line bg-surface py-2 pl-3 pr-1 text-[13px] shadow-[0_12px_32px_-12px_rgb(0_0_0/0.45)] ${notice.tone === "success" ? "border-l-ok" : "border-l-danger"}`}
          onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}>
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${notice.tone === "success" ? "bg-ok" : "bg-danger"}`} aria-hidden />
          <span className="min-w-0 break-words">{notice.message}</span>
          <button type="button" aria-label="Dismiss notification" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-ui text-muted hover:bg-sunken hover:text-fg"
            onClick={() => { setHovered(false); setFocused(false); dismissSaveNotification(); }}><CloseIcon className="h-3.5 w-3.5" /></button>
        </div>}
      </div>
    </div>
  );
}
