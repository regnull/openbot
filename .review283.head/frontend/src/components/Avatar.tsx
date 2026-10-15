import { botIconFor } from "../lib/botIcons";

const HUMAN_GLYPH = botIconFor("person").glyph;
const SYSTEM_GLYPH = botIconFor("gear").glyph;

/**
 * Who said it. Every kind shares the same sunken tile so a row of participants reads as one
 * family; only the border and glyph color set them apart. People get a solid border and the
 * brightest glyph (they're always the one operator); bots carry their chosen glyph in accent;
 * system lines get a dashed outline and a gear so they read as machine output.
 */
export default function Avatar({ name, kind, small, icon }: { name: string; kind: string; small?: boolean; icon?: string | null | undefined }) {
  // Message payloads call the current participant "user", while participant records use "human".
  // Treat both as the same person so the avatar stays consistent in every view.
  const isHuman = kind === "human" || kind === "user";
  const isSystem = kind === "system";
  const cls =
    isHuman ? "border-fg bg-sunken text-fg"
    : kind === "external" ? "border-line bg-sunken text-muted"
    : isSystem ? "border-dashed border-line-strong bg-transparent text-muted"
    : "border-line bg-sunken text-accent-strong";
  const dims = small ? "h-10 w-10 text-sm" : "h-12 w-12 text-base";
  const glyph = isHuman ? HUMAN_GLYPH : isSystem ? SYSTEM_GLYPH : icon ? botIconFor(icon).glyph : null;
  return (
    <span title={name} aria-label={name} className={`inline-flex ${dims} shrink-0 items-center justify-center rounded-ui border font-medium leading-none ${cls} ${glyph ? (small ? "text-base" : "text-lg") : ""}`}>
      {glyph ?? name.slice(0, 2).toUpperCase()}
    </span>
  );
}
