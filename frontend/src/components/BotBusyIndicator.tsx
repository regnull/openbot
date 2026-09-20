/**
 * Bot Busy/Waiting Indicator — "Quiet Presence"
 *
 * A dignified, minimal waiting state shown inline in the thread message list while
 * a bot is processing. Uses a single pulsing dot + status text to communicate
 * activity without demanding attention.
 *
 * Replaces ThinkingPlaceholder for queued/running runs with no content yet.
 * Fades out smoothly when the bot finishes, and supports reduced-motion preferences.
 */
import { useCallback, useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react";
import Avatar from "./Avatar";

type Status = "busy" | "timed_out";

interface Props {
  botName: string;
  icon?: string | null;
  status?: Status;
}

/** Imperative handle exposed so a parent can trigger the exit transition. */
export interface BotBusyIndicatorHandle {
  /** Trigger the exit fade-out animation. */
  exit: () => void;
}

/**
 * BotBusyIndicator
 *
 * Renders an inline message-sheet with the bot's avatar, a pulsing dot, and
 * status text. The parent calls `ref.current.exit()` to start the fade-out
 * and receives `onTransitionComplete` when the animation finishes.
 *
 * For the simpler case (MessageList), the indicator is simply unmounted when
 * the run gets content — no imperative handle needed. The exit animation is
 * used when the parent wants a smooth visual transition (e.g. in a run card
 * that replaces the indicator in-place).
 */
const BotBusyIndicator = forwardRef<BotBusyIndicatorHandle, Props & { onTransitionComplete?: () => void }>(
  function BotBusyIndicator({ botName, icon, status = "busy", onTransitionComplete }, ref) {
    const [exiting, setExiting] = useState(false);
    const [hidden, setHidden] = useState(false);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const exit = useCallback(() => {
      if (exiting || hidden) return;
      setExiting(true);
      timerRef.current = setTimeout(() => {
        setHidden(true);
        onTransitionComplete?.();
      }, 320);
    }, [exiting, hidden, onTransitionComplete]);

    useImperativeHandle(ref, () => ({ exit }), [exit]);

    useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

    if (hidden) return null;

    const label = status === "timed_out" ? "Timed out" : "busy, waiting\u2026";

    return (
      <div
        className={`bot-busy-indicator message-sheet message-assistant flex items-center gap-3 ${exiting ? "bot-busy-exit" : ""}`}
        role="status"
        aria-live="polite"
        aria-label={`${botName} is ${status === "timed_out" ? "timed out" : "busy, waiting for response"}`}
      >
        <Avatar name={botName} kind="bot" icon={icon} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="bot-busy-dot shrink-0" aria-hidden="true" />
            <span className="truncate text-[13px] leading-snug text-muted">
              <span className="font-medium text-fg">{botName}</span>{" "}
              <span className="text-faint">—</span>{" "}
              <span>{label}</span>
            </span>
          </div>
        </div>
      </div>
    );
  }
);

export default BotBusyIndicator;
