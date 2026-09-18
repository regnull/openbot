import { describe, expect, it } from "vitest";
import { shouldRedirectAfterSetup } from "./setupRedirect";

describe("shouldRedirectAfterSetup", () => {
  it("redirects when setup transitions from incomplete to complete", () => {
    expect(shouldRedirectAfterSetup(true, true)).toBe(true);
  });

  it("does not redirect an already configured user", () => {
    expect(shouldRedirectAfterSetup(false, true)).toBe(false);
  });

  it("does not redirect while setup remains incomplete", () => {
    expect(shouldRedirectAfterSetup(true, false)).toBe(false);
  });
});
