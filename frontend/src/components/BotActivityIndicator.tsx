export default function BotActivityIndicator({ active, showLabel = false }: { active: boolean; showLabel?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={active ? "Active" : "Idle"}>
      <span className={`h-2 w-2 rounded-full ${active ? "animate-pulse bg-green-500" : "bg-zinc-300 dark:bg-zinc-700"}`} />
      {showLabel && <span className="text-xs text-zinc-500">{active ? "Active" : "Idle"}</span>}
    </span>
  );
}
