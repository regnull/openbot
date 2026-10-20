/**
 * Canvas 2D drawing for the office's screens and signs. Everything is demo UI fed by the
 * mock simulation; nothing here reads OpenBot production data.
 */
import { isLand } from "../../../lib/office/worldMap";

export type Ctx = CanvasRenderingContext2D;

export const UI = {
  bg: "#081327", panel: "#0d1d3a", panel2: "#112649", line: "#1e3a66", text: "#e8f1ff", dim: "#8aa4cc", faint: "#4f6a94",
  cyan: "#38d6f5", blue: "#3b82f6", green: "#34d399", amber: "#fbbf24", red: "#f87171", navy: "#16213E", cream: "#F6F4EF", orange: "#DD7A3D",
};
export const SANS = '"IBM Plex Sans", "Helvetica Neue", Arial, sans-serif';
export const MONO = '"IBM Plex Mono", Menlo, monospace';
export const SCRIPT = '"Bradley Hand", "Segoe Print", "Comic Sans MS", "Chalkboard SE", cursive';

export function rrect(g: Ctx, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

export function text(g: Ctx, s: string, x: number, y: number, size: number, color = UI.text, weight = 500, font = SANS, align: CanvasTextAlign = "left") {
  g.font = `${weight} ${size}px ${font}`;
  g.fillStyle = color;
  g.textAlign = align;
  g.textBaseline = "alphabetic";
  g.fillText(s, x, y);
}

export function fitText(g: Ctx, s: string, max: number): string {
  if (g.measureText(s).width <= max) return s;
  let t = s;
  while (t.length > 1 && g.measureText(t + "…").width > max) t = t.slice(0, -1);
  return t + "…";
}

/** The OpenBot mark (logo-icon.svg): navy tile, cream hexagon bubble, orange tail, two eyes. */
export function logo(g: Ctx, x: number, y: number, s: number, tile = true) {
  const k = s / 256;
  g.save();
  g.translate(x, y);
  g.scale(k, k);
  if (tile) {
    g.fillStyle = UI.navy;
    rrect(g, 0, 0, 256, 256, 56);
    g.fill();
  }
  g.fillStyle = UI.cream;
  g.beginPath();
  for (const [px, py] of [[192, 110], [160, 165.4], [96, 165.4], [64, 110], [96, 54.6], [160, 54.6]]) g.lineTo(px, py);
  g.closePath();
  g.fill();
  g.fillStyle = UI.orange;
  g.beginPath();
  g.moveTo(108, 165.4);
  g.lineTo(128, 165.4);
  g.lineTo(92, 198);
  g.closePath();
  g.fill();
  g.fillStyle = UI.navy;
  for (const cx of [110, 146]) {
    g.beginPath();
    g.arc(cx, 100, 9, 0, Math.PI * 2);
    g.fill();
  }
  g.restore();
}

export function panel(g: Ctx, x: number, y: number, w: number, h: number, title?: string, size = 14) {
  g.fillStyle = UI.panel;
  rrect(g, x, y, w, h, Math.min(10, h / 6));
  g.fill();
  g.strokeStyle = UI.line;
  g.lineWidth = 1.5;
  g.stroke();
  if (title) text(g, title.toUpperCase(), x + 12, y + size + 8, size, UI.dim, 600);
}

export function bar(g: Ctx, x: number, y: number, w: number, h: number, v: number, color = UI.cyan) {
  g.fillStyle = "#16305a";
  rrect(g, x, y, w, h, h / 2);
  g.fill();
  if (v > 0) {
    g.fillStyle = color;
    rrect(g, x, y, Math.max(h, w * Math.min(1, v)), h, h / 2);
    g.fill();
  }
}

export function ring(g: Ctx, cx: number, cy: number, r: number, v: number, color = UI.cyan, width = 8) {
  g.lineWidth = width;
  g.strokeStyle = "#16305a";
  g.beginPath();
  g.arc(cx, cy, r, 0, Math.PI * 2);
  g.stroke();
  g.strokeStyle = color;
  g.lineCap = "round";
  g.beginPath();
  g.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.min(1, Math.max(0.001, v)));
  g.stroke();
  g.lineCap = "butt";
}

export function spark(g: Ctx, x: number, y: number, w: number, h: number, vals: number[], color = UI.cyan, fill = true) {
  const n = vals.length;
  const max = Math.max(...vals, 1e-6);
  g.beginPath();
  vals.forEach((v, i) => {
    const px = x + (i / (n - 1)) * w, py = y + h - (v / max) * h;
    if (i) g.lineTo(px, py); else g.moveTo(px, py);
  });
  g.strokeStyle = color;
  g.lineWidth = 2.5;
  g.stroke();
  if (fill) {
    g.lineTo(x + w, y + h);
    g.lineTo(x, y + h);
    g.closePath();
    const grad = g.createLinearGradient(0, y, 0, y + h);
    grad.addColorStop(0, "rgba(56,214,245,0.35)");
    grad.addColorStop(1, "rgba(56,214,245,0)");
    g.fillStyle = grad;
    g.fill();
  }
}

export function bars(g: Ctx, x: number, y: number, w: number, h: number, vals: number[], highlight = -1) {
  const n = vals.length;
  const max = Math.max(...vals, 1e-6);
  const bw = (w / n) * 0.62;
  vals.forEach((v, i) => {
    const bh = (v / max) * h;
    const grad = g.createLinearGradient(0, y + h - bh, 0, y + h);
    grad.addColorStop(0, i === highlight ? "#7cf0ff" : "#4f8ef7");
    grad.addColorStop(1, i === highlight ? "#2bc4e6" : "#2563eb");
    g.fillStyle = grad;
    rrect(g, x + i * (w / n) + (w / n - bw) / 2, y + h - bh, bw, bh, Math.min(4, bw / 3));
    g.fill();
  });
}

let mapCache: { w: number; h: number; pts: [number, number][] } | null = null;
/** Dotted equirectangular world map. */
export function worldMap(g: Ctx, x: number, y: number, w: number, h: number, color = "rgba(80,190,255,0.85)", dot = 2.2, step = 9) {
  if (!mapCache || mapCache.w !== w || mapCache.h !== h) {
    const pts: [number, number][] = [];
    for (let py = 0; py < h; py += step) {
      for (let px = 0; px < w; px += step) {
        const lon = (px / w) * 360 - 180, lat = 85 - (py / h) * 145;
        if (isLand(lon, lat)) pts.push([px, py]);
      }
    }
    mapCache = { w, h, pts };
  }
  g.fillStyle = color;
  for (const [px, py] of mapCache.pts) {
    g.beginPath();
    g.arc(x + px, y + py, dot, 0, Math.PI * 2);
    g.fill();
  }
}

export function glowDot(g: Ctx, x: number, y: number, r: number, color: string) {
  const grad = g.createRadialGradient(x, y, 0, x, y, r * 3);
  grad.addColorStop(0, color);
  grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad;
  g.beginPath();
  g.arc(x, y, r * 3, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = "#ffffff";
  g.beginPath();
  g.arc(x, y, r * 0.6, 0, Math.PI * 2);
  g.fill();
}

/** Deterministic pseudo-random for decorative screen content. */
export function hash(n: number): number {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}
