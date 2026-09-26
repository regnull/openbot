import { describe, expect, it } from "vitest";
import { logoSrc, usesHashRouting } from "./desktop";

describe("desktop build helpers", () => {
  it("uses hash routing only for the file:// build", () => {
    expect(usesHashRouting("file:")).toBe(true);
    expect(usesHashRouting("http:")).toBe(false);
    expect(usesHashRouting("https:")).toBe(false);
  });

  it("resolves the logo against the Vite base", () => {
    expect(logoSrc).toBe(`${import.meta.env.BASE_URL}logo-icon.svg`);
  });
});
