import { CanvasTexture, Color, LinearFilter, Mesh, MeshStandardMaterial, SRGBColorSpace, Vector3 } from "three";
import type { OfficeScene } from "./officeAssets";
import {
  MONO, SANS, SCRIPT, UI, bar, bars, fitText, glowDot, hash, logo, ring, rrect, spark, text, worldMap, type Ctx,
} from "./screenArt";

/** What the screens show: a read-out of the mock simulation (demo data only). */
export interface ScreenData {
  t: number;
  phase: string;
  task: { title: string; status: string; progress: number; subtasks: { title: string; agent: string; progress: number; status: string }[] } | null;
  agents: { name: string; role: string; status: string; label: string; tone: string }[];
  completed: number;
  inProgress: number;
  active: number;
  helpers: number;
  alerts: string[];
  log: string[];
  /** Desk item id -> what its occupant is doing ("coding", "seated" …), for the desk monitors. */
  desks: Record<string, string>;
  blocked: boolean;
}

interface ScreenSlot {
  name: string;
  mesh: Mesh;
  canvas: HTMLCanvasElement;
  g: Ctx;
  texture: CanvasTexture;
  material: MeshStandardMaterial;
  w: number;
  h: number;
  interval: number;
  last: number;
  paint: (g: Ctx, w: number, h: number, d: ScreenData, t: number) => void;
}

/** Canvas pixels repainted (and uploaded) per frame at most. */
const PIXEL_BUDGET = 600_000;

const TONE: Record<string, string> = { calm: UI.dim, active: UI.cyan, warn: UI.amber, danger: UI.red, ok: UI.green, rest: "#a78bfa" };

/**
 * Paints CanvasTextures onto the office's SCREEN_* (emissive displays) and SIGN_* (lit
 * signage) quads. Each slot repaints at its own modest rate; signs paint once.
 */
export class ScreenPainter {
  private readonly slots: ScreenSlot[] = [];
  private readonly signs: ScreenSlot[] = [];
  private maxAnisotropy: number;
  private slow = false;

  constructor(office: OfficeScene, maxAnisotropy: number) {
    this.maxAnisotropy = maxAnisotropy;
    for (const [name, mesh] of office.screens) {
      const p = this.screenPainter(name);
      this.slots.push(this.slot(name, mesh, p.ppm, p.max, p.interval, p.paint, true));
    }
    for (const [name, mesh] of office.signs) {
      const p = this.signPainter(name);
      this.signs.push(this.slot(name, mesh, p.ppm, 2048, Infinity, p.paint, false));
    }
  }

  /** Reduced quality: halve the repaint rate. */
  setSlow(slow: boolean) {
    this.slow = slow;
  }

  private slot(name: string, mesh: Mesh, ppm: number, max: number, interval: number, paint: ScreenSlot["paint"], emissive: boolean): ScreenSlot {
    mesh.geometry.computeBoundingBox();
    const size = mesh.geometry.boundingBox!.getSize(new Vector3());
    const scale = mesh.getWorldScale(new Vector3());
    const dims = [size.x * scale.x, size.y * scale.y, size.z * scale.z].sort((a, b) => b - a);
    const wm = dims[0], hm = dims[1];
    let w = Math.round(wm * ppm), h = Math.round(hm * ppm);
    const k = Math.min(1, max / Math.max(w, h));
    w = Math.max(64, Math.round(w * k));
    h = Math.max(40, Math.round(h * k));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const g = canvas.getContext("2d")!;
    const texture = new CanvasTexture(canvas);
    texture.colorSpace = SRGBColorSpace;
    texture.flipY = false; // glTF UV convention: v = 0 is the top row
    texture.anisotropy = Math.min(8, this.maxAnisotropy);
    texture.minFilter = LinearFilter;
    texture.generateMipmaps = false;
    const material = emissive
      ? new MeshStandardMaterial({ color: "#04070d", roughness: 0.22, metalness: 0, emissive: new Color("#ffffff"), emissiveMap: texture,
        emissiveIntensity: name.startsWith("SCREEN_Command_P") || name === "SCREEN_Ops_Wall" ? 1.35 : 1.0 })
      : new MeshStandardMaterial({ map: texture, roughness: 0.85, metalness: 0 });
    material.name = `${name}_Material`;
    mesh.material = material;
    return { name, mesh, canvas, g, texture, material, w, h, interval, last: -Infinity, paint };
  }

  /**
   * Repaints the slots that are due, a few per call (oldest first), so texture uploads spread
   * over frames instead of landing in one.
   */
  update(d: ScreenData, now: number, force = false) {
    const k = this.slow ? 2 : 1;
    const due = force ? this.slots : this.slots.filter((s) => now - s.last >= s.interval * k).sort((a, b) => a.last - b.last);
    let pixels = 0;
    for (const s of due) {
      if (!force && pixels > PIXEL_BUDGET) break;
      pixels += s.w * s.h;
      s.last = now;
      s.g.save();
      s.paint(s.g, s.w, s.h, d, now);
      s.g.restore();
      s.texture.needsUpdate = true;
    }
  }

  paintSigns() {
    for (const s of this.signs) {
      s.g.save();
      s.paint(s.g, s.w, s.h, EMPTY, 0);
      s.g.restore();
      s.texture.needsUpdate = true;
    }
  }

  get count() {
    return { screens: this.slots.length, signs: this.signs.length };
  }

  dispose() {
    for (const s of [...this.slots, ...this.signs]) {
      s.texture.dispose();
      s.material.dispose();
    }
  }

  // ------------------------------------------------------------------ screen painters
  private screenPainter(name: string): { ppm: number; max: number; interval: number; paint: ScreenSlot["paint"] } {
    if (name === "SCREEN_Ops_Wall") return { ppm: 480, max: 1920, interval: 1, paint: opsWall };
    if (name === "SCREEN_Reporting_Screen") return { ppm: 700, max: 1280, interval: 0.4, paint: reportingScreen };
    const cp = /^SCREEN_Command_P(\d)$/.exec(name);
    if (cp) return { ppm: 520, max: 640, interval: 0.4, paint: commandPanel(Number(cp[1])) };
    const cm = /^SCREEN_Command_Mon_(\d)$/.exec(name);
    if (cm) return { ppm: 1100, max: 320, interval: 0.6, paint: consoleMonitor(Number(cm[1])) };
    if (name.startsWith("SCREEN_Ops_Console") || name.startsWith("SCREEN_Ops_Station")) {
      return { ppm: 800, max: 320, interval: 0.6, paint: opsConsole(name.endsWith("_1") ? 1 : 0) };
    }
    if (name === "SCREEN_Lobby_Kiosk") return { ppm: 1000, max: 320, interval: 2, paint: kiosk("Welcome", "Check in here") };
    if (name === "SCREEN_Ops_Terminal") return { ppm: 1000, max: 320, interval: 1, paint: kiosk("Service", "Terminal ready") };
    if (name === "SCREEN_Test_Bench") return { ppm: 1200, max: 200, interval: 0.25, paint: scope };
    const wall = /^SCREEN_(Dev_Desk_\d)_Desk_Wall$/.exec(name);
    if (wall) return { ppm: 700, max: 640, interval: 0.6, paint: pipelineWall(wall[1]) };
    const desk = /^SCREEN_(.+)_Desk_(\d)$/.exec(name);
    if (desk) return { ppm: 900, max: 384, interval: 0.5, paint: deskMonitor(desk[1], Number(desk[2])) };
    return { ppm: 600, max: 512, interval: 2, paint: idleScreen };
  }

  private signPainter(name: string): { ppm: number; paint: ScreenSlot["paint"] } {
    switch (name) {
      case "SIGN_Lobby_Transom": return { ppm: 900, paint: transom };
      case "SIGN_WelcomeMat": return { ppm: 700, paint: welcomeMat };
      case "SIGN_Quote_FrontL": return { ppm: 420, paint: quote(["Different skills.", "Same bigger tomorrow."], "#F3F2EE") };
      case "SIGN_Quote_FrontR": return { ppm: 420, paint: quote(["Good ideas lead to", "brighter tomorrows."], "#F3F2EE", true) };
      case "SIGN_Quote_Break": return { ppm: 640, paint: quote(["Better helpers,", "happier tomorrows."], "#F3F2EE") };
      case "SIGN_Research_Board": return { ppm: 760, paint: whiteboard };
      case "SIGN_Command_Header": return { ppm: 900, paint: commandHeader };
      default: return { ppm: 500, paint: (g, w, h) => { g.fillStyle = "#F3F2EE"; g.fillRect(0, 0, w, h); } };
    }
  }
}

const EMPTY: ScreenData = { t: 0, phase: "", task: null, agents: [], completed: 0, inProgress: 0, active: 0, helpers: 0, alerts: [], log: [], desks: {}, blocked: false };

// ==================================================================== big displays
function background(g: Ctx, w: number, h: number, bright = false) {
  const grad = g.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, bright ? "#123d86" : "#0b1a36");
  grad.addColorStop(1, bright ? "#0a2459" : "#06112a");
  g.fillStyle = grad;
  g.fillRect(0, 0, w, h);
  g.strokeStyle = "rgba(56,130,246,0.08)";
  g.lineWidth = 1;
  for (let x = 0; x < w; x += 24) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
  for (let y = 0; y < h; y += 24) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
}

function demoTag(g: Ctx, x: number, y: number, s = 12) {
  g.font = `600 ${s}px ${SANS}`;
  const tw = g.measureText("DEMO DATA").width;
  g.fillStyle = "rgba(251,191,36,0.16)";
  rrect(g, x - tw - s, y - s * 1.2, tw + s * 1.4, s * 1.7, s * 0.5);
  g.fill();
  text(g, "DEMO DATA", x - s * 0.3, y, s, UI.amber, 600, SANS, "right");
}

function commandPanel(k: number) {
  return (g: Ctx, w: number, h: number, d: ScreenData, t: number) => {
    background(g, w, h, true);
    const p = w * 0.06;
    if (k === 2) {
      // centre: the 3D globe floats in front; keep this panel calm (radial glow + live counters)
      const grad = g.createRadialGradient(w / 2, h * 0.42, 10, w / 2, h * 0.42, w * 0.6);
      grad.addColorStop(0, "#123a73");
      grad.addColorStop(1, "#071530");
      g.fillStyle = grad;
      g.fillRect(0, 0, w, h);
      for (let r = 1; r <= 3; r++) {
        g.strokeStyle = `rgba(56,214,245,${0.12 + 0.05 * Math.sin(t * 1.5 + r)})`;
        g.lineWidth = 2;
        g.beginPath();
        g.arc(w / 2, h * 0.42, w * (0.18 + r * 0.1), 0, Math.PI * 2);
        g.stroke();
      }
      text(g, "LIVE", p, p + 18, 16, UI.cyan, 600);
      text(g, String(d.active), w / 2 - w * 0.2, h * 0.88, 44, UI.text, 600, SANS, "center");
      text(g, "ACTIVE", w / 2 - w * 0.2, h * 0.94, 13, UI.cyan, 600, SANS, "center");
      text(g, String(d.helpers), w / 2 + w * 0.2, h * 0.88, 44, UI.text, 600, SANS, "center");
      text(g, "HELPERS", w / 2 + w * 0.2, h * 0.94, 13, UI.cyan, 600, SANS, "center");
    } else if (k === 3) {
      // brand panel
      const grad = g.createLinearGradient(0, 0, w, h);
      grad.addColorStop(0, "#0e2a5c");
      grad.addColorStop(1, "#081733");
      g.fillStyle = grad;
      g.fillRect(0, 0, w, h);
      logo(g, p, p + 10, w * 0.2);
      text(g, "OpenBot", p, h * 0.42, w * 0.15, UI.text, 600);
      text(g, "AI HELPERS", p, h * 0.56, w * 0.085, UI.cyan, 600);
      text(g, "REAL IMPACT", p, h * 0.66, w * 0.085, UI.text, 600);
      text(g, "Small helpers. Big possibilities.", p, h * 0.8, w * 0.045, UI.dim, 400);
      bar(g, p, h * 0.88, w - 2 * p, 8, (Math.sin(t * 0.6) + 1.2) / 2.4);
    } else if (k === 1) {
      // task overview
      text(g, "TASK OVERVIEW", p, p + 18, 18, UI.dim, 600);
      if (!d.task) {
        text(g, "Waiting for a task…", p, h * 0.22, 22, UI.text, 500);
      } else {
        g.font = `600 26px ${SANS}`;
        text(g, fitText(g, d.task.title, w - 2 * p), p, h * 0.2, 26, UI.text, 600);
        text(g, d.phase, p, h * 0.27, 16, d.blocked ? UI.red : UI.cyan, 500);
        let y = h * 0.36;
        for (const st of d.task.subtasks) {
          g.font = `500 17px ${SANS}`;
          text(g, fitText(g, `${st.title}`, w * 0.62), p, y, 17, UI.text, 500);
          text(g, st.agent, w - p, y, 15, UI.dim, 500, SANS, "right");
          bar(g, p, y + 10, w - 2 * p, 9, st.progress, st.status === "blocked" ? UI.red : st.status === "completed" ? UI.green : UI.cyan);
          y += h * 0.14;
        }
      }
      demoTag(g, w - p, h - p * 0.7, 13);
    } else if (k === 0) {
      text(g, "AGENTS", p, p + 18, 18, UI.dim, 600);
      let y = p + 56;
      for (const a of d.agents) {
        g.fillStyle = TONE[a.tone] ?? UI.dim;
        g.beginPath();
        g.arc(p + 7, y - 6, 6, 0, Math.PI * 2);
        g.fill();
        text(g, a.name, p + 22, y, 18, UI.text, 600);
        text(g, a.label, w - p, y, 14, UI.dim, 500, SANS, "right");
        y += (h - p * 2 - 40) / Math.max(6, d.agents.length);
      }
    } else {
      text(g, "ACTIVITY", p, p + 18, 18, UI.dim, 600);
      const vals = Array.from({ length: 24 }, (_, i) => 0.4 + 0.5 * hash(i + Math.floor(t / 3)) + (i > 18 ? d.active * 0.08 : 0));
      spark(g, p, h * 0.12, w - 2 * p, h * 0.25, vals);
      text(g, `${d.completed}`, p, h * 0.52, 44, UI.text, 600);
      text(g, "TASKS COMPLETED", p, h * 0.58, 14, UI.cyan, 600);
      let y = h * 0.68;
      for (const line of d.log.slice(-4).reverse()) {
        g.font = `400 14px ${SANS}`;
        text(g, fitText(g, line, w - 2 * p), p, y, 14, UI.dim, 400);
        y += 24;
      }
    }
  };
}

function consoleMonitor(k: number) {
  return (g: Ctx, w: number, h: number, d: ScreenData, t: number) => {
    background(g, w, h);
    const p = 10;
    if (k === 2) {
      ring(g, w / 2, h / 2 + 4, h * 0.3, d.task?.progress ?? 0, d.blocked ? UI.red : UI.cyan, 9);
      text(g, `${Math.round((d.task?.progress ?? 0) * 100)}%`, w / 2, h / 2 + 12, 22, UI.text, 600, SANS, "center");
    } else if (k === 0 || k === 4) {
      bars(g, p, p + 20, w - 2 * p, h - 2 * p - 22, Array.from({ length: 8 }, (_, i) => 0.3 + hash(i + k * 13 + Math.floor(t)) * 0.7), 7);
      text(g, k === 0 ? "LOAD" : "QUEUE", p, p + 12, 12, UI.dim, 600);
    } else {
      worldMap(g, p, p + 4, w - 2 * p, h - 2 * p - 8, "rgba(80,200,255,0.65)", 1.4, 6);
      text(g, k === 1 ? `${d.active} active` : d.blocked ? "1 alert" : "all clear", p, h - 8, 13, d.blocked && k === 3 ? UI.red : UI.cyan, 600);
    }
  };
}

function reportingScreen(g: Ctx, w: number, h: number, d: ScreenData, t: number) {
  // bright analytics slide, as in the approved design
  const grad = g.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, "#f7fbff");
  grad.addColorStop(1, "#e9f2fd");
  g.fillStyle = grad;
  g.fillRect(0, 0, w, h);
  const p = w * 0.045;
  logo(g, p, p * 0.7, h * 0.07);
  text(g, "OpenBot · Weekly results", p + h * 0.09, p * 0.7 + h * 0.055, h * 0.035, "#4a5d80", 600);
  text(g, "Today", p, h * 0.3, h * 0.075, UI.navy, 600);
  text(g, "Brighter", p, h * 0.39, h * 0.075, UI.navy, 600);
  text(g, "Together", p, h * 0.48, h * 0.075, UI.navy, 600);
  const vals = [3, 5, 4, 6, 5 + d.completed, 7 + d.completed];
  bars(g, w * 0.36, h * 0.18, w * 0.36, h * 0.52, vals, vals.length - 1);
  g.strokeStyle = "#c9d8ee";
  g.lineWidth = 2;
  g.beginPath();
  g.moveTo(w * 0.35, h * 0.705);
  g.lineTo(w * 0.73, h * 0.705);
  g.stroke();
  ring(g, w * 0.86, h * 0.33, h * 0.12, d.task?.progress ?? 1, "#2563eb", h * 0.03);
  text(g, `${Math.round((d.task?.progress ?? 1) * 100)}%`, w * 0.86, h * 0.35, h * 0.05, UI.navy, 600, SANS, "center");
  text(g, "CURRENT TASK", w * 0.86, h * 0.52, h * 0.028, "#5b6f92", 600, SANS, "center");
  let y = h * 0.62;
  for (const st of (d.task?.subtasks ?? []).slice(0, 4)) {
    g.fillStyle = st.status === "completed" ? "#10b981" : st.status === "blocked" ? "#ef4444" : "#3b82f6";
    g.beginPath();
    g.arc(w * 0.79, y - h * 0.012, h * 0.011, 0, Math.PI * 2);
    g.fill();
    g.font = `500 ${h * 0.03}px ${SANS}`;
    text(g, fitText(g, st.title, w * 0.17), w * 0.805, y, h * 0.03, "#22314f", 500);
    y += h * 0.058;
  }
  text(g, d.task ? fitText(g, d.task.title, w * 0.6) : "No active task", p, h * 0.82, h * 0.04, "#22314f", 600);
  text(g, `${d.completed} completed · ${d.inProgress} in progress`, p, h * 0.9, h * 0.032, "#5b6f92", 500);
  demoTag(g, w - p, h - p * 0.6, h * 0.026);
  void t;
}

function opsWall(g: Ctx, w: number, h: number, d: ScreenData, t: number) {
  background(g, w, h);
  const p = h * 0.07;
  text(g, "OPS · SYSTEM HEALTH", p, p + h * 0.04, h * 0.05, UI.dim, 600);
  const mapW = w * 0.52;
  worldMap(g, p, h * 0.18, mapW, h * 0.7, "rgba(70,170,255,0.75)", h * 0.007, Math.max(8, h * 0.022));
  const sites = [[0.22, 0.32], [0.48, 0.28], [0.52, 0.55], [0.75, 0.36], [0.83, 0.7], [0.3, 0.62]];
  sites.forEach(([sx, sy], i) => glowDot(g, p + sx * mapW, h * 0.18 + sy * h * 0.7, h * 0.01 + 2 * Math.sin(t * 2 + i), i === 2 && d.blocked ? "rgba(248,113,113,0.8)" : "rgba(56,214,245,0.7)"));
  // a pulse ring
  const cx = w * 0.62, cy = h * 0.55;
  ring(g, cx, cy, h * 0.18, 0.999, d.blocked ? UI.red : UI.cyan, h * 0.012);
  text(g, d.blocked ? "!" : "OK", cx, cy + h * 0.045, h * 0.13, d.blocked ? UI.red : UI.cyan, 600, SANS, "center");
  // systems list
  const x0 = w * 0.74;
  text(g, "Systems", x0, h * 0.22, h * 0.08, UI.text, 600);
  const rows: [string, string, boolean][] = [
    ["Online", d.blocked ? "97%" : "100%", !d.blocked], ["Helpers", String(d.helpers), true], ["Tasks", String(24 + d.completed), true], ["Uptime", "99.9%", true],
  ];
  rows.forEach(([k, v, ok], i) => {
    const y = h * (0.36 + i * 0.14);
    g.fillStyle = ok ? UI.green : UI.amber;
    g.beginPath();
    g.arc(x0 + h * 0.02, y - h * 0.025, h * 0.016, 0, Math.PI * 2);
    g.fill();
    text(g, k, x0 + h * 0.06, y, h * 0.065, UI.text, 500);
    text(g, v, w - p, y, h * 0.07, UI.text, 600, SANS, "right");
  });
  if (d.blocked || d.alerts.length) {
    g.fillStyle = "rgba(248,113,113,0.18)";
    rrect(g, p, h * 0.84, mapW, h * 0.1, h * 0.03);
    g.fill();
    text(g, `ALERT · ${d.alerts[0] ?? "Check failed"}`, p + h * 0.03, h * 0.91, h * 0.05, UI.red, 600);
  }
  demoTag(g, w - p, h - p * 0.5, h * 0.035);
}

function opsConsole(k: number) {
  return (g: Ctx, w: number, h: number, d: ScreenData, t: number) => {
    background(g, w, h);
    if (k === 0) {
      text(g, "LOGS", 10, 22, 14, UI.dim, 600);
      let y = 44;
      for (let i = 0; i < 7; i++) {
        const bad = d.blocked && i === 6;
        g.fillStyle = bad ? UI.red : hash(i + Math.floor(t * 2)) > 0.2 ? "#2f6db3" : UI.cyan;
        rrect(g, 10, y, (w - 20) * (0.4 + 0.6 * hash(i * 7 + Math.floor(t))), 8, 4);
        g.fill();
        y += 22;
      }
    } else {
      spark(g, 10, 30, w - 20, h - 50, Array.from({ length: 20 }, (_, i) => 0.5 + 0.5 * Math.sin(i * 0.7 + t)), d.blocked ? UI.red : UI.cyan);
      text(g, "LATENCY", 10, 22, 14, UI.dim, 600);
    }
  };
}

function kiosk(title: string, sub: string) {
  return (g: Ctx, w: number, h: number) => {
    const grad = g.createLinearGradient(0, 0, w, h);
    grad.addColorStop(0, "#0e2a5c");
    grad.addColorStop(1, "#091a38");
    g.fillStyle = grad;
    g.fillRect(0, 0, w, h);
    logo(g, w * 0.08, h * 0.18, h * 0.36);
    text(g, title, w * 0.08 + h * 0.44, h * 0.38, h * 0.16, UI.text, 600);
    text(g, sub, w * 0.08 + h * 0.44, h * 0.52, h * 0.1, UI.cyan, 500);
    g.fillStyle = UI.cyan;
    rrect(g, w * 0.08, h * 0.7, w * 0.84, h * 0.16, h * 0.08);
    g.fill();
    text(g, "Tap to start", w / 2, h * 0.815, h * 0.09, UI.navy, 600, SANS, "center");
  };
}

function scope(g: Ctx, w: number, h: number, d: ScreenData, t: number) {
  g.fillStyle = "#03140f";
  g.fillRect(0, 0, w, h);
  g.strokeStyle = d.blocked ? "#f87171" : "#34d399";
  g.lineWidth = 2;
  g.beginPath();
  for (let x = 0; x < w; x++) {
    const y = h / 2 + Math.sin(x * 0.12 + t * 6) * h * 0.25 * (d.blocked ? (x % 30 < 15 ? 1 : 0.2) : 1);
    if (x) g.lineTo(x, y); else g.moveTo(x, y);
  }
  g.stroke();
}

function pipelineWall(desk: string) {
  return (g: Ctx, w: number, h: number, d: ScreenData, t: number) => {
    background(g, w, h);
    const p = w * 0.05;
    text(g, desk === "Dev_Desk_1" ? "CI PIPELINE" : "TEST RUNS", p, p + 16, 18, UI.dim, 600);
    const stages = ["build", "unit", "integr.", "deploy"];
    stages.forEach((s, i) => {
      const x = p + i * ((w - 2 * p) / 4);
      const bad = d.blocked && i === 2;
      const done = !bad && (i < 2 || !d.blocked);
      g.fillStyle = bad ? "rgba(248,113,113,0.25)" : done ? "rgba(52,211,153,0.2)" : "rgba(56,130,246,0.2)";
      rrect(g, x, h * 0.32, (w - 2 * p) / 4 - 10, h * 0.3, 10);
      g.fill();
      text(g, s, x + 10, h * 0.45, 17, bad ? UI.red : done ? UI.green : UI.cyan, 600);
      text(g, bad ? "failed" : done ? "passed" : "running", x + 10, h * 0.55, 13, UI.dim, 500);
    });
    spark(g, p, h * 0.7, w - 2 * p, h * 0.22, Array.from({ length: 30 }, (_, i) => 0.6 + 0.4 * Math.sin(i * 0.5 + t * 0.7)), d.blocked ? UI.red : UI.cyan);
  };
}

function deskMonitor(desk: string, k: number) {
  const seed = [...desk].reduce((a, c) => a + c.charCodeAt(0), 0) + k * 31;
  return (g: Ctx, w: number, h: number, d: ScreenData, t: number) => {
    const state = d.desks[desk];
    const active = state === "coding" || state === "working" || state === "testing" || state === "thinking";
    g.fillStyle = "#0a1428";
    g.fillRect(0, 0, w, h);
    if (!state) {
      // nobody here: a calm screensaver
      const grad = g.createLinearGradient(0, 0, w, h);
      grad.addColorStop(0, "#0f2650");
      grad.addColorStop(1, "#0a1630");
      g.fillStyle = grad;
      g.fillRect(0, 0, w, h);
      logo(g, w / 2 - h * 0.17, h * 0.26, h * 0.34, false);
      return;
    }
    // title bar
    g.fillStyle = "#13264a";
    g.fillRect(0, 0, w, h * 0.12);
    for (let i = 0; i < 3; i++) {
      g.fillStyle = ["#f87171", "#fbbf24", "#34d399"][i];
      g.beginPath();
      g.arc(h * 0.06 + i * h * 0.07, h * 0.06, h * 0.022, 0, Math.PI * 2);
      g.fill();
    }
    if (k % 2 === 0) {
      // code editor, scrolling while the Openling types
      const scroll = active ? Math.floor(t * 3) : 0;
      const lh = h * 0.075;
      for (let i = 0; i < 11; i++) {
        const n = i + scroll + seed;
        const y = h * 0.17 + i * lh;
        g.fillStyle = "#3a5585";
        g.font = `400 ${lh * 0.55}px ${MONO}`;
        g.fillText(String((n % 90) + 1).padStart(2, " "), w * 0.03, y + lh * 0.5);
        const indent = (Math.floor(hash(n) * 3)) * w * 0.05;
        let x = w * 0.12 + indent;
        const parts = 1 + Math.floor(hash(n + 1) * 3);
        for (let j = 0; j < parts; j++) {
          const len = w * (0.08 + hash(n * 3 + j) * 0.22);
          g.fillStyle = ["#7dd3fc", "#c4b5fd", "#86efac", "#fcd34d", "#94a3b8"][Math.floor(hash(n + j * 5) * 5)];
          rrect(g, x, y + lh * 0.22, Math.min(len, w * 0.95 - x), lh * 0.42, lh * 0.2);
          g.fill();
          x += len + w * 0.02;
          if (x > w * 0.9) break;
        }
      }
      if (active && Math.floor(t * 2) % 2 === 0) {
        g.fillStyle = UI.cyan;
        g.fillRect(w * 0.5, h * 0.17 + 10 * lh + lh * 0.15, w * 0.012, lh * 0.6);
      }
    } else {
      // dashboard
      text(g, d.blocked && desk.startsWith("Desk") ? "build: waiting" : "insights", w * 0.05, h * 0.24, h * 0.07, UI.dim, 600);
      bars(g, w * 0.05, h * 0.3, w * 0.5, h * 0.55, Array.from({ length: 6 }, (_, i) => 0.3 + hash(i + seed + Math.floor(t / 2)) * 0.7), 5);
      ring(g, w * 0.78, h * 0.55, h * 0.2, active ? (Math.sin(t * 0.3 + seed) + 1) / 2 : 0.6, UI.cyan, h * 0.05);
    }
  };
}

function idleScreen(g: Ctx, w: number, h: number) {
  g.fillStyle = "#0b1730";
  g.fillRect(0, 0, w, h);
  logo(g, w / 2 - h * 0.2, h * 0.3, h * 0.4, false);
}

// ==================================================================== signs
function transom(g: Ctx, w: number, h: number) {
  g.fillStyle = "#1A2744";
  g.fillRect(0, 0, w, h);
  const s = h * 0.72;
  logo(g, w * 0.5 - s * 2.6, (h - s) / 2, s, false);
  text(g, "OpenBot", w * 0.5 - s * 1.5, h * 0.68, h * 0.5, UI.cream, 600);
  text(g, "WORK BRIGHTER TOGETHER", w * 0.5 + s * 1.35, h * 0.62, h * 0.2, "#9fb4d8", 600);
}

function welcomeMat(g: Ctx, w: number, h: number) {
  g.fillStyle = "#1D2A49";
  g.fillRect(0, 0, w, h);
  // woven texture
  g.strokeStyle = "rgba(255,255,255,0.035)";
  for (let y = 0; y < h; y += 4) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
  g.strokeStyle = "rgba(160,190,240,0.35)";
  g.lineWidth = h * 0.012;
  rrect(g, h * 0.05, h * 0.05, w - h * 0.1, h * 0.9, h * 0.04);
  g.stroke();
  const s = h * 0.34;
  logo(g, w / 2 - s / 2, h * 0.1, s, false);
  text(g, "OpenBot", w / 2, h * 0.68, h * 0.2, "#eef3ff", 600, SANS, "center");
  g.font = `500 ${h * 0.085}px ${SANS}`;
  g.fillStyle = "#b8c8e8";
  g.textAlign = "center";
  const word = "W E L C O M E";
  g.fillText(word, w / 2, h * 0.86);
}

function quote(lines: string[], wall: string, smile = false) {
  return (g: Ctx, w: number, h: number) => {
    g.fillStyle = wall;
    g.fillRect(0, 0, w, h);
    let size = h / (lines.length + 0.55);
    // shrink to fit the widest line in the sign
    g.font = `400 ${size * 0.9}px ${SCRIPT}`;
    const widest = Math.max(...lines.map((l) => g.measureText(l).width));
    const room = w * (smile ? 0.72 : 0.9);
    if (widest > room) size *= room / widest;
    lines.forEach((l, i) => text(g, l, w * 0.05, size * (i + 0.95), size * 0.9, "#24386b", 400, SCRIPT));
    // blue underline swoosh
    g.strokeStyle = "#3b82f6";
    g.lineWidth = Math.max(3, h * 0.03);
    g.lineCap = "round";
    g.beginPath();
    g.moveTo(w * 0.06, size * (lines.length + 0.2));
    g.quadraticCurveTo(w * 0.3, size * (lines.length + 0.02), w * 0.55, size * (lines.length + 0.12));
    g.stroke();
    if (smile) {
      const cx = w * 0.86, cy = h * 0.5, r = h * 0.26;
      g.lineWidth = Math.max(3, h * 0.025);
      g.strokeStyle = "#3b6fd0";
      g.beginPath();
      g.arc(cx, cy, r, 0, Math.PI * 2);
      g.stroke();
      g.beginPath();
      g.arc(cx, cy + r * 0.05, r * 0.55, 0.2 * Math.PI, 0.8 * Math.PI);
      g.stroke();
      g.fillStyle = "#3b6fd0";
      for (const dx of [-0.32, 0.32]) {
        g.beginPath();
        g.arc(cx + dx * r, cy - r * 0.25, r * 0.08, 0, Math.PI * 2);
        g.fill();
      }
    }
  };
}

function whiteboard(g: Ctx, w: number, h: number) {
  g.fillStyle = "#fcfcfa";
  g.fillRect(0, 0, w, h);
  text(g, "Ideas today.", w * 0.08, h * 0.32, h * 0.15, "#2a4f9a", 400, SCRIPT);
  text(g, "A brighter", w * 0.08, h * 0.52, h * 0.15, "#2a4f9a", 400, SCRIPT);
  text(g, "tomorrow.", w * 0.08, h * 0.72, h * 0.15, "#2a4f9a", 400, SCRIPT);
  g.strokeStyle = "#3b82f6";
  g.lineWidth = h * 0.018;
  g.lineCap = "round";
  g.beginPath();
  g.moveTo(w * 0.09, h * 0.82);
  g.quadraticCurveTo(w * 0.3, h * 0.77, w * 0.5, h * 0.8);
  g.stroke();
  // a doodled lightbulb and arrows
  const cx = w * 0.78, cy = h * 0.38;
  g.strokeStyle = "#f59e0b";
  g.lineWidth = h * 0.014;
  g.beginPath();
  g.arc(cx, cy, h * 0.12, Math.PI * 0.8, Math.PI * 2.2);
  g.lineTo(cx + h * 0.05, cy + h * 0.2);
  g.lineTo(cx - h * 0.05, cy + h * 0.2);
  g.closePath();
  g.stroke();
  for (let i = 0; i < 5; i++) {
    const a = -Math.PI * 0.9 + i * Math.PI * 0.2;
    g.beginPath();
    g.moveTo(cx + Math.cos(a) * h * 0.17, cy + Math.sin(a) * h * 0.17);
    g.lineTo(cx + Math.cos(a) * h * 0.23, cy + Math.sin(a) * h * 0.23);
    g.stroke();
  }
  g.fillStyle = "rgba(56,130,246,0.15)";
  rrect(g, w * 0.66, h * 0.66, w * 0.26, h * 0.2, 8);
  g.fill();
  text(g, "research → build → test", w * 0.68, h * 0.78, h * 0.05, "#2a4f9a", 400, SCRIPT);
}

function commandHeader(g: Ctx, w: number, h: number) {
  g.fillStyle = "#FAF9F6";
  g.fillRect(0, 0, w, h);
  const s = h * 0.7;
  logo(g, w * 0.5 - s * 3.2, (h - s) / 2, s);
  text(g, "OpenBot", w * 0.5 - s * 2.2, h * 0.68, h * 0.48, UI.navy, 600);
  text(g, "SMALL HELPERS. BIG POSSIBILITIES.", w * 0.5 + s * 0.7, h * 0.6, h * 0.2, "#4a5d80", 600);
}
