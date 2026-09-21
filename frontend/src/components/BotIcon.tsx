import { botIconFor } from "../lib/botIcons";

export default function BotIcon({ icon, className = "", bare = false }: { icon: string | null | undefined; className?: string; bare?: boolean }) {
  const option = botIconFor(icon);
  const enclosure = bare ? "" : "rounded-ui border border-line bg-sunken";
  return (
    <span
      aria-label={option.label}
      title={option.label}
      className={`inline-flex h-12 w-12 shrink-0 items-center justify-center ${enclosure} text-xl leading-none ${className}`}
    >
      {option.glyph}
    </span>
  );
}
