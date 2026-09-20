export default function BotActivityIndicator({ active, showLabel = false }: { active: boolean; showLabel?: boolean }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5" title={active ? "Active" : "Idle"}>
      <span className={`h-1.5 w-1.5 rounded-full ${active ? "live-dot bg-ok" : "bg-line-strong"}`} />
      {showLabel && <span className={`text-[11px] leading-4 ${active ? "text-ok" : "text-faint"}`}>{active ? "active" : "idle"}</span>}
    </span>
  );
}
