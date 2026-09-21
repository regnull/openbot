import { botIconFor } from "../lib/botIcons";

export default function BotIcon({ icon, className = "" }: { icon: string | null | undefined; className?: string }) {
  const option = botIconFor(icon);
  return (
    <span
      aria-label={option.label}
      title={option.label}
      className={`inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-ui border border-line bg-sunken text-xl leading-none ${className}`}
    >
      {option.glyph}
    </span>
  );
}
