import { describe, expect, it } from "vitest";
import { nextVersion, parseMajorMinor } from "./version.cjs";

describe("release version", () => {
  it("parses the hand-maintained major.minor", () => {
    expect(parseMajorMinor("0.1\n")).toEqual({ major: 0, minor: 1 });
    expect(parseMajorMinor("  12.34 ")).toEqual({ major: 12, minor: 34 });
  });

  it("rejects a VERSION file that is not exactly major.minor", () => {
    for (const bad of ["", "1", "1.2.3", "v1.2", "1.x", "01.2"]) {
      expect(() => parseMajorMinor(bad)).toThrow(/VERSION/);
    }
  });

  it("starts the build number at 1 when nothing has been released", () => {
    expect(nextVersion("0.1", [])).toBe("0.1.1");
  });

  it("continues the build number across major.minor bumps", () => {
    expect(nextVersion("0.1", ["v0.1.1", "v0.1.2"])).toBe("0.1.3");
    expect(nextVersion("0.2", ["v0.1.1", "v0.1.7"])).toBe("0.2.8");
    expect(nextVersion("1.0", ["v0.2.9", "v0.1.12"])).toBe("1.0.13");
  });

  it("ignores tags that are not release versions", () => {
    expect(nextVersion("0.1", ["v0.1.4", "v0.1.99-rc", "nightly", "0.1.50", "v0.1"])).toBe("0.1.5");
  });

  it("refuses a major.minor that would sort before the latest release", () => {
    expect(() => nextVersion("0.1", ["v0.2.3"])).toThrow(/0\.2\.3/);
  });
});
