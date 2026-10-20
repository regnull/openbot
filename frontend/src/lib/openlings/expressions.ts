/**
 * Facial expressions of the Openling: morph targets on the Openling_Face mesh, authored in
 * Blender with the character. Neutral is the approved face (all weights
 * zero). Each expression has a face target (brows, mouth) and a separate eye target, so
 * a blink can blend the expression's eyes toward the closed eye instead of adding two eye
 * deltas, which would push vertices past the closed line.
 */
export type OpenlingExpression = "Neutral" | "Happy" | "Focused" | "Worried" | "Reporting";

export const EXPRESSIONS: readonly { id: OpenlingExpression; label: string }[] = [
  { id: "Neutral", label: "Neutral" },
  { id: "Happy", label: "Happy" },
  { id: "Focused", label: "Focused" },
  { id: "Worried", label: "Worried" },
  { id: "Reporting", label: "Reporting" },
];

export const MORPH_TARGETS = [
  "Exp_Happy", "Exp_Happy_Eyes", "Exp_Focused", "Exp_Focused_Eyes", "Exp_Worried", "Exp_Worried_Eyes",
  "Exp_Reporting", "Exp_Reporting_Eyes", "Blink_L", "Blink_R",
] as const;
export type MorphTarget = (typeof MORPH_TARGETS)[number];

/** How closed an expression's own eyes are: Happy's "^ ^" arcs are already shut, so a blink adds nothing. */
const EYES_CLOSED: Record<OpenlingExpression, number> = { Neutral: 0, Happy: 1, Focused: 0, Worried: 0, Reporting: 0 };

export type ExpressionMix = Partial<Record<OpenlingExpression, number>>;

/**
 * Morph weights for a blend of expressions (weights summing to at most 1) plus a blink in
 * [0, 1]. The eye targets stay a convex combination: sum(expression eyes) + blink <= 1.
 */
export function morphWeights(mix: ExpressionMix, blink: number): Record<MorphTarget, number> {
  const out = Object.fromEntries(MORPH_TARGETS.map((m) => [m, 0])) as Record<MorphTarget, number>;
  let closed = 0;
  for (const [id, w = 0] of Object.entries(mix) as [OpenlingExpression, number][]) closed += w * EYES_CLOSED[id];
  const b = clamp01(blink) * (1 - clamp01(closed));
  for (const [id, w = 0] of Object.entries(mix) as [OpenlingExpression, number][]) {
    if (id === "Neutral" || w <= 0) continue;
    out[`Exp_${id}` as MorphTarget] = w;
    out[`Exp_${id}_Eyes` as MorphTarget] = w * (1 - b);
  }
  out.Blink_L = out.Blink_R = b;
  return out;
}

/** Moves a mix toward a single expression by `step` (0..1), keeping the total at 1. */
export function stepMix(mix: ExpressionMix, target: OpenlingExpression, step: number): ExpressionMix {
  const s = clamp01(step);
  const next: ExpressionMix = {};
  for (const e of EXPRESSIONS) {
    const w = mix[e.id] ?? (e.id === "Neutral" && Object.keys(mix).length === 0 ? 1 : 0);
    const goal = e.id === target ? 1 : 0;
    const v = w + (goal - w) * s;
    if (v > 1e-4) next[e.id] = v;
  }
  return next;
}

/** Blink shape over its duration: a fast close, a short hold, a slower open. */
export function blinkAmount(t: number, duration = BLINK_SECONDS): number {
  if (t <= 0 || t >= duration) return 0;
  const x = t / duration;
  if (x < 0.35) return smooth(x / 0.35);
  if (x < 0.5) return 1;
  return 1 - smooth((x - 0.5) / 0.5);
}

export const BLINK_SECONDS = 0.18;

/** Seconds until the next blink: 2.2-5.6 s, with an occasional quick double blink. */
export function nextBlinkDelay(random: () => number): number {
  return random() < 0.12 ? 0.32 : 2.2 + random() * 3.4;
}

/** Small seeded PRNG (mulberry32) so each Openling blinks on its own schedule, reproducibly. */
export function seededRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const smooth = (x: number) => x * x * (3 - 2 * x);
