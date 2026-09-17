import { botIconFor } from "../lib/botIcons";

const colors = ["bg-rose-500", "bg-amber-500", "bg-emerald-500", "bg-sky-500", "bg-violet-500", "bg-fuchsia-500"];

export default function Avatar({ name, kind, small, icon }: { name: string; kind: string; small?: boolean; icon?: string | null | undefined }) {
  const idx = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % colors.length;
  const cls = kind === "human" ? "bg-zinc-700" : kind === "external" ? "bg-zinc-400" : kind === "system" ? "bg-zinc-300 text-zinc-700" : colors[idx];
  const dims = small ? "h-6 w-6 text-[10px]" : "h-8 w-8 text-xs";
  return (
    <span title={name} className={`inline-flex ${dims} shrink-0 items-center justify-center rounded-full border-2 border-white font-bold text-white dark:border-zinc-900 ${cls}`}>
      {icon ? botIconFor(icon).glyph : name.slice(0, 2).toUpperCase()}
    </span>
  );
}