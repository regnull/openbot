import { describe, expect, it } from "vitest";
import { normalizeWorkingDirectory } from "./workingDirectory";

describe("normalizeWorkingDirectory", () => {
  it("defaults blank and dot input to the workspace root", () => {
    expect(normalizeWorkingDirectory("").value).toBeNull();
    expect(normalizeWorkingDirectory("  .  ").value).toBeNull();
  });

  it("normalizes a custom relative directory", () => {
    expect(normalizeWorkingDirectory(" project\\src/ ")).toEqual({ ok: true, value: "project/src", error: null });
  });

  it("rejects unsafe paths before submitting", () => {
    for (const path of ["../x", "project/../x", "/tmp", "C:\\tmp", "bad\npath"]) {
      const result = normalizeWorkingDirectory(path);
      expect(result.ok, path).toBe(false);
      expect(result.error, path).toBeTruthy();
    }
  });
});
