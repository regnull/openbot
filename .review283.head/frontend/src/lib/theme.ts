/**
 * Theme preference: "system" follows the OS, "light"/"dark" pin it.
 * The choice lives in localStorage and is mirrored onto <html data-theme>; index.html applies it
 * before first paint so the page never flashes the wrong theme. Stylesheets read the attribute
 * (see index.css), so this module never touches colors itself.
 */
export type Theme = "system" | "light" | "dark";
export const THEME_KEY = "openbot:theme";
export const THEMES: Theme[] = ["system", "light", "dark"];

type Root = { setAttribute(n: string, v: string): void; removeAttribute(n: string): void };

export function readTheme(storage: Pick<Storage, "getItem"> | null = safeStorage()): Theme {
  try {
    const v = storage?.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch { return "system"; }
}

/** Persists the preference and mirrors it onto the document root. */
export function applyTheme(theme: Theme, root: Root | null = safeRoot(), storage: Pick<Storage, "setItem" | "removeItem"> | null = safeStorage()): void {
  try {
    if (theme === "system") storage?.removeItem(THEME_KEY); else storage?.setItem(THEME_KEY, theme);
  } catch { /* storage may be unavailable; the attribute still applies for this page */ }
  if (!root) return;
  if (theme === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", theme);
}

/** The next preference in the cycle system → light → dark → system. */
export function nextTheme(current: Theme): Theme {
  return THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
}

function safeStorage(): Storage | null {
  try { return typeof localStorage === "undefined" ? null : localStorage; } catch { return null; }
}
function safeRoot(): Root | null {
  return typeof document === "undefined" ? null : document.documentElement;
}
