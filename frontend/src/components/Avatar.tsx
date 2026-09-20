import { botIconFor } from "../lib/botIcons";

/**
 * Who said it. People are the inverted square (ink on paper, paper on ink); bots carry their
 * chosen glyph on a sunken tile; system lines get a dashed outline so they read as machine output.
 */
export default function Avatar({ name, kind, small, icon }: { name: string; kind: string; small?: boolean; icon?: string | null | undefined }) {
  const cls =
    kind === "human" ? "border-fg bg-fg text-canvas"
    : kind === "external" ? "border-line bg-sunken text-muted"
    : kind === "system" ? "border-dashed border-line-strong bg-transparent text-muted"
    : "border-line bg-sunken text-accent-strong";
  const dims = small ? "h-8 w-8 text-xs" : "h-10 w-10 text-sm";
  const glyph = icon ? botIconFor(icon).glyph : null;
  return (
    <span title={name} className={`inline-flex ${dims} shrink-0 items-center justify-center rounded-ui border font-medium leading-none ${cls} ${glyph ? (small ? "text-sm" : "text-base") : ""}`}>
      {glyph ?? name.slice(0, 2).toUpperCase()}
    </span>
  );
}
