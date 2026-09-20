/**
 * Inline placeholder shown in the thread message list while a bot is processing.
 * Positioned exactly where the bot's response will eventually appear.
 *
 * Lightweight: no RunCard, just the bot's avatar + name + animated dots.
 * Disappears once the run gets events/streaming or a message is posted.
 */
import Avatar from "./Avatar";

export default function ThinkingPlaceholder({ botName, icon }: { botName: string; icon?: string | null }) {
  return (
    <div className="message-sheet message-assistant flex gap-3" role="status" aria-label={`${botName} is thinking`}>
      <Avatar name={botName} kind="bot" icon={icon} />
      <div className="min-w-0 flex-1">
        <div className="message-meta"><span className="font-medium text-fg">{botName}</span></div>
        <div className="flex items-center gap-1.5 text-xs text-muted">
          <span>is thinking</span>
          <span className="inline-flex gap-0.5" aria-hidden>
            <span className="thinking-dot h-1 w-1 rounded-full bg-accent" style={{ animationDelay: "0ms" }} />
            <span className="thinking-dot h-1 w-1 rounded-full bg-accent" style={{ animationDelay: "200ms" }} />
            <span className="thinking-dot h-1 w-1 rounded-full bg-accent" style={{ animationDelay: "400ms" }} />
          </span>
        </div>
      </div>
    </div>
  );
}
