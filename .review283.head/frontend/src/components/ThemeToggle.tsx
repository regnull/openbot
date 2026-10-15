import { useState } from "react";
import { applyTheme, nextTheme, readTheme, THEMES, type Theme } from "../lib/theme";
import { MonitorIcon, MoonIcon, SunIcon } from "./icons";

const LABEL: Record<Theme, string> = { system: "Follow system theme", light: "Light theme", dark: "Dark theme" };
const Icon = ({ theme, className }: { theme: Theme; className?: string }) =>
  theme === "light" ? <SunIcon className={className} /> : theme === "dark" ? <MoonIcon className={className} /> : <MonitorIcon className={className} />;

/**
 * Light / dark / system. Expanded: a three-way segmented control. Compact: one button that cycles.
 * The preference is applied immediately and remembered for the next visit.
 */
export default function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const choose = (t: Theme) => { applyTheme(t); setTheme(t); };
  if (compact) {
    return (
      <button type="button" onClick={() => choose(nextTheme(theme))} aria-label={`${LABEL[theme]}. Click to change`} title={LABEL[theme]}
        className="inline-flex h-8 w-8 items-center justify-center rounded-ui text-muted hover:bg-sunken hover:text-fg">
        <Icon theme={theme} className="h-4 w-4" />
      </button>
    );
  }
  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-ui border border-line p-0.5">
      {THEMES.map((t) => (
        <button key={t} type="button" role="radio" aria-checked={theme === t} aria-label={LABEL[t]} title={LABEL[t]} onClick={() => choose(t)}
          className={`inline-flex h-6 w-7 items-center justify-center rounded-[2px] transition-colors ${theme === t ? "bg-sunken text-fg" : "text-faint hover:text-muted"}`}>
          <Icon theme={t} className="h-3.5 w-3.5" />
        </button>
      ))}
    </div>
  );
}
