export interface BotIconOption { key: string; label: string; glyph: string; }

export const DEFAULT_BOT_ICON = "robot";
export const BOT_ICONS: BotIconOption[] = [
  { key: "robot", label: "Robot", glyph: "🤖" },
  { key: "briefcase", label: "Briefcase", glyph: "💼" },
  { key: "code", label: "Code", glyph: "💻" },
  { key: "search", label: "Search", glyph: "🔎" },
  { key: "test-tube", label: "Test tube", glyph: "🧪" },
  { key: "shield", label: "Shield", glyph: "🛡️" },
  { key: "sparkles", label: "Sparkles", glyph: "✨" },
  { key: "chat", label: "Chat", glyph: "💬" },
  { key: "brain", label: "Brain", glyph: "🧠" },
  { key: "rocket", label: "Rocket", glyph: "🚀" },
];

export function botIconFor(key: string | null | undefined): BotIconOption {
  return BOT_ICONS.find((icon) => icon.key === key) ?? BOT_ICONS[0];
}
