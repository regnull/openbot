import { describe, expect, it } from "vitest";
import { applyTheme, nextTheme, readTheme, THEME_KEY } from "./theme";

function fakeStorage(initial: Record<string, string> = {}) {
  const m = new Map(Object.entries(initial));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, removeItem: (k: string) => { m.delete(k); }, map: m };
}
function fakeRoot() {
  const attrs = new Map<string, string>();
  return { setAttribute: (n: string, v: string) => { attrs.set(n, v); }, removeAttribute: (n: string) => { attrs.delete(n); }, attrs };
}

describe("theme preference", () => {
  it("reads a stored light/dark choice and falls back to system for anything else", () => {
    expect(readTheme(fakeStorage({ [THEME_KEY]: "dark" }))).toBe("dark");
    expect(readTheme(fakeStorage({ [THEME_KEY]: "light" }))).toBe("light");
    expect(readTheme(fakeStorage({ [THEME_KEY]: "purple" }))).toBe("system");
    expect(readTheme(fakeStorage())).toBe("system");
    expect(readTheme(null)).toBe("system");
  });
  it("mirrors the choice onto the root and clears both when following the system", () => {
    const storage = fakeStorage();
    const root = fakeRoot();
    applyTheme("dark", root, storage);
    expect(root.attrs.get("data-theme")).toBe("dark");
    expect(storage.map.get(THEME_KEY)).toBe("dark");
    applyTheme("system", root, storage);
    expect(root.attrs.has("data-theme")).toBe(false);
    expect(storage.map.has(THEME_KEY)).toBe(false);
  });
  it("survives a storage that throws", () => {
    const root = fakeRoot();
    const broken = { setItem: () => { throw new Error("quota"); }, removeItem: () => { throw new Error("quota"); } };
    expect(() => applyTheme("light", root, broken)).not.toThrow();
    expect(root.attrs.get("data-theme")).toBe("light");
  });
  it("cycles system → light → dark → system", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });
});
