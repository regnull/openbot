import { describe, expect, it } from "vitest";
import { modKeyLabel } from "./shortcuts";

describe("modKeyLabel", () => {
  it("uses the command key on Apple platforms", () => {
    expect(modKeyLabel("MacIntel")).toBe("⌘");
    expect(modKeyLabel("iPad")).toBe("⌘");
  });

  it("uses Ctrl everywhere else", () => {
    expect(modKeyLabel("Win32")).toBe("Ctrl+");
    expect(modKeyLabel("Linux x86_64")).toBe("Ctrl+");
    expect(modKeyLabel("")).toBe("Ctrl+");
  });
});
