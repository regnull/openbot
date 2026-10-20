/**
 * Khronos PBR Neutral tone mapping — the view transform of the Blender lookdev renders and
 * three.js' `NeutralToneMapping`. Used to pre-compensate flat backdrop colours so that, after the
 * renderer tone-maps the whole frame, they land on the exact pixel values of the references.
 * https://github.com/KhronosGroup/ToneMapping/tree/main/PBR_Neutral
 */
export type RGB = [number, number, number];

const START_COMPRESSION = 0.8 - 0.04;
const DESATURATION = 0.15;

/** Tone-maps a linear RGB colour (same maths as three.js `NeutralToneMapping`). */
export function neutralToneMap([r, g, b]: RGB): RGB {
  const x = Math.min(r, g, b);
  const offset = x < 0.08 ? x - 6.25 * x * x : 0.04;
  let c: RGB = [r - offset, g - offset, b - offset];
  const peak = Math.max(...c);
  if (peak < START_COMPRESSION) return c;
  const d = 1 - START_COMPRESSION;
  const newPeak = 1 - (d * d) / (peak + d - START_COMPRESSION);
  c = c.map((v) => (v * newPeak) / peak) as RGB;
  const t = 1 - 1 / (DESATURATION * (peak - newPeak) + 1);
  return c.map((v) => v + (newPeak - v) * t) as RGB;
}

/**
 * The linear colour that tone-maps to `target` (each channel in [0, 1)), undoing the curve's
 * steps in reverse: desaturation and highlight compression (driven by the peak channel), then the
 * toe offset (driven by the smallest channel).
 */
export function inverseNeutralToneMap(target: RGB): RGB {
  let c: RGB = [...target];
  const newPeak = Math.max(...c);
  if (newPeak >= START_COMPRESSION) {
    const d = 1 - START_COMPRESSION;
    const peak = (d * d) / (1 - newPeak) - d + START_COMPRESSION;
    const t = 1 - 1 / (DESATURATION * (peak - newPeak) + 1);
    c = c.map((v) => ((v - newPeak * t) / (1 - t)) * (peak / newPeak)) as RGB;
  }
  // Forward: offset = x - 6.25x² below x = 0.08 (so min(out) = 6.25x²), else 0.04.
  const m = Math.min(...c);
  const offset = m < 0.04 ? Math.sqrt(Math.max(0, m) / 6.25) - Math.max(0, m) : 0.04;
  return c.map((v) => v + offset) as RGB;
}

export function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}
