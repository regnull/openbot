/** Label for the primary shortcut modifier: ⌘ on Apple platforms, Ctrl elsewhere. */
export function modKeyLabel(platform: string): string {
  return /mac|iphone|ipad|ipod/i.test(platform) ? "⌘" : "Ctrl+";
}

export const modKey = modKeyLabel(typeof navigator === "undefined" ? "" : navigator.platform);
