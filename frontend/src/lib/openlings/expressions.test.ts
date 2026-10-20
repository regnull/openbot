import { describe, expect, it } from "vitest";
import { BLINK_SECONDS, EXPRESSIONS, MORPH_TARGETS, blinkAmount, morphWeights, nextBlinkDelay, seededRandom, stepMix } from "./expressions";

const eyeSum = (w: Record<string, number>) =>
  Object.entries(w).filter(([k]) => k.endsWith("_Eyes")).reduce((s, [, v]) => s + v, 0) + w.Blink_L;

describe("Openling expressions", () => {
  it("leaves every morph at zero for Neutral, so the approved face is untouched", () => {
    const w = morphWeights({ Neutral: 1 }, 0);
    expect(Object.values(w).every((v) => v === 0)).toBe(true);
    expect(Object.keys(w).sort()).toEqual([...MORPH_TARGETS].sort());
  });

  it("drives the face and eye targets of the chosen expression", () => {
    const w = morphWeights({ Focused: 1 }, 0);
    expect(w.Exp_Focused).toBe(1);
    expect(w.Exp_Focused_Eyes).toBe(1);
    expect(w.Exp_Happy).toBe(0);
  });

  it("blends expression eyes toward the closed eye instead of adding deltas", () => {
    for (const e of EXPRESSIONS) {
      for (const blink of [0, 0.3, 0.7, 1]) {
        expect(eyeSum(morphWeights({ [e.id]: 1 }, blink))).toBeLessThanOrEqual(1 + 1e-9);
      }
    }
    const closed = morphWeights({ Worried: 1 }, 1);
    expect(closed.Exp_Worried_Eyes).toBe(0);
    expect(closed.Blink_L).toBe(1);
    expect(closed.Exp_Worried).toBe(1); // brows and mouth stay while blinking
  });

  it("does not blink over Happy's already-closed smiling eyes", () => {
    const w = morphWeights({ Happy: 1 }, 1);
    expect(w.Blink_L).toBe(0);
    expect(w.Exp_Happy_Eyes).toBe(1);
  });

  it("crossfades between expressions keeping the total weight at 1", () => {
    let mix = stepMix({}, "Neutral", 1);
    expect(mix.Neutral).toBeCloseTo(1);
    mix = stepMix(mix, "Happy", 0.5);
    const total = Object.values(mix).reduce((a, b) => a + (b ?? 0), 0);
    expect(total).toBeCloseTo(1, 6);
    expect(mix.Happy).toBeCloseTo(0.5);
    for (let i = 0; i < 40; i++) mix = stepMix(mix, "Happy", 0.3);
    expect(mix.Happy).toBeCloseTo(1, 3);
    expect(mix.Neutral ?? 0).toBeLessThan(1e-3);
  });

  it("closes fully during a blink and is open outside it", () => {
    expect(blinkAmount(-0.01)).toBe(0);
    expect(blinkAmount(BLINK_SECONDS * 0.42)).toBe(1);
    expect(blinkAmount(BLINK_SECONDS + 0.01)).toBe(0);
    expect(blinkAmount(BLINK_SECONDS * 0.2)).toBeGreaterThan(0);
  });

  it("gives each seed its own blink schedule", () => {
    const a = seededRandom(1), b = seededRandom(2);
    const da = Array.from({ length: 6 }, () => nextBlinkDelay(a));
    const db = Array.from({ length: 6 }, () => nextBlinkDelay(b));
    expect(da).not.toEqual(db);
    for (const d of [...da, ...db]) expect(d === 0.32 || (d >= 2.2 && d <= 5.6)).toBe(true);
    const again = seededRandom(1);
    expect(Array.from({ length: 6 }, () => nextBlinkDelay(again))).toEqual(da);
  });
});
