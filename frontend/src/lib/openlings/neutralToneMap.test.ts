import { describe, expect, it } from "vitest";
import { inverseNeutralToneMap, neutralToneMap, srgbToLinear, type RGB } from "./neutralToneMap";

describe("Khronos PBR Neutral tone map", () => {
  it("is close to identity in the mid-tones, shifted by the 0.04 offset", () => {
    expect(neutralToneMap([0.5, 0.5, 0.5])[0]).toBeCloseTo(0.46, 6);
  });

  it("compresses highlights below 1", () => {
    expect(neutralToneMap([4, 4, 4])[0]).toBeLessThan(1);
    expect(neutralToneMap([4, 4, 4])[0]).toBeGreaterThan(neutralToneMap([2, 2, 2])[0]);
  });

  it("inverts greys across the toe, the linear part and the shoulder", () => {
    for (const v of [0.01, 0.05, 0.3, 0.75, 0.8, 0.95, 0.99]) {
      expect(neutralToneMap(inverseNeutralToneMap([v, v, v]))[0]).toBeCloseTo(v, 5);
    }
  });

  it("inverts near-white colours without shifting their hue", () => {
    // The studio floor and wall: per-channel inversion would tint these warm.
    for (const hex of ["#f9f8f7", "#d4d4d6", "#efeff0"]) {
      const target = [1, 3, 5].map((i) => srgbToLinear(parseInt(hex.slice(i, i + 2), 16) / 255)) as RGB;
      const out = neutralToneMap(inverseNeutralToneMap(target));
      out.forEach((v, c) => expect(v).toBeCloseTo(target[c], 4));
    }
  });

  it("converts sRGB to linear", () => {
    expect(srgbToLinear(0)).toBe(0);
    expect(srgbToLinear(1)).toBeCloseTo(1, 6);
    expect(srgbToLinear(0.5)).toBeCloseTo(0.214, 3);
  });
});
