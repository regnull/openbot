import { Scene, Vector3, type PerspectiveCamera } from "three";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import type { AgentId } from "../../../lib/office/agents";
import type { OfficeWall } from "../../../lib/office/layout";
import { STATUS, bubbleFor, type AgentStatus, type BubbleIcon } from "../../../lib/office/status";

export interface BubbleInfo {
  id: AgentId;
  name: string;
  role: string;
  status: AgentStatus;
  detail: string;
  task: string | null;
  progress: number | null;
}

const ICONS: Record<BubbleIcon, string> = {
  dots: '<svg viewBox="0 0 24 24"><circle cx="6" cy="12" r="2.2"/><circle cx="12" cy="12" r="2.2"/><circle cx="18" cy="12" r="2.2"/></svg>',
  hourglass: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><path d="M7 4h10M7 20h10M8 4c0 5 8 5 8 8s-8 3-8 8M16 4c0 5-8 5-8 8s8 3 8 8"/></svg>',
  bulb: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/></svg>',
  code: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/></svg>',
  checklist: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6l1.5 1.5L8 5M4 12l1.5 1.5L8 11M4 18l1.5 1.5L8 17M11 6.5h9M11 12.5h9M11 18.5h9"/></svg>',
  alert: '<svg viewBox="0 0 24 24"><path d="M12 5.2v9" stroke-width="3" stroke-linecap="round" fill="none"/><circle cx="12" cy="19" r="1.8"/></svg>',
  review: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  chart: '<svg viewBox="0 0 24 24"><rect x="4" y="12" width="3.5" height="8" rx="1"/><rect x="10.2" y="7" width="3.5" height="13" rx="1"/><rect x="16.4" y="3.5" width="3.5" height="16.5" rx="1"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  rest: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><path d="M19 14.5A7.5 7.5 0 1 1 9.5 5a6 6 0 0 0 9.5 9.5z"/></svg>',
  zzz: '<svg viewBox="0 0 28 24"><text x="2" y="19" font-size="13" font-weight="700" font-family="IBM Plex Sans, sans-serif">z</text><text x="10" y="14" font-size="11" font-weight="700" font-family="IBM Plex Sans, sans-serif">Z</text><text x="18" y="9" font-size="9" font-weight="700" font-family="IBM Plex Sans, sans-serif">z</text></svg>',
};

const STYLE = `
.ob-bubbles { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.ob-bubble { position: absolute; pointer-events: auto; cursor: pointer; transform-origin: 50% 100%; }
.ob-bubble[data-hidden="1"] { visibility: hidden; }
.ob-b-inner { position: relative; display: flex; flex-direction: column; align-items: center; transform: translateY(var(--lift, 0px)) scale(var(--s, 1));
  transform-origin: 50% 100%; transition: transform 160ms ease-out, opacity 200ms ease-out; }
.ob-b-pill { display: flex; align-items: center; justify-content: center; width: 30px; height: 26px; border-radius: 10px; background: #ffffff;
  border: 1.5px solid #8fb6f2; box-shadow: 0 3px 10px rgba(22,33,62,0.18), 0 1px 2px rgba(22,33,62,0.12); color: #2563eb; }
.ob-b-pill svg { width: 17px; height: 17px; fill: currentColor; stroke: currentColor; }
.ob-b-tail { width: 9px; height: 9px; margin-top: -5px; background: #ffffff; border-right: 1.5px solid #8fb6f2; border-bottom: 1.5px solid #8fb6f2;
  transform: rotate(45deg); }
.ob-bubble[data-tone="danger"] .ob-b-pill { background: #ef4444; border-color: #dc2626; color: #ffffff; border-radius: 50%; width: 26px; }
.ob-bubble[data-tone="danger"] .ob-b-tail { background: #ef4444; border-color: #dc2626; }
.ob-bubble[data-icon="review"] .ob-b-pill { background: #fff7ed; border-color: #f97316; color: #ea580c; border-radius: 10px; width: 30px; }
.ob-bubble[data-icon="review"] .ob-b-tail { background: #fff7ed; border-color: #f97316; }
.ob-bubble[data-tone="ok"] .ob-b-pill { background: #10b981; border-color: #059669; color: #ffffff; border-radius: 50%; width: 26px; }
.ob-bubble[data-tone="ok"] .ob-b-tail { background: #10b981; border-color: #059669; }
.ob-bubble[data-tone="rest"] .ob-b-pill { color: #4f6bd8; }
.ob-bubble[data-icon="zzz"] .ob-b-pill { width: 36px; }
.ob-bubble[data-icon="zzz"] svg { width: 24px; animation: ob-zzz 2.8s ease-in-out infinite; }
.ob-bubble[data-tone="calm"] .ob-b-pill { color: #64748b; border-color: #c4d2e6; }
.ob-bubble[data-pop="1"] .ob-b-inner { animation: ob-pop 260ms ease-out; }
.ob-bubble[data-selected="1"] .ob-b-pill { box-shadow: 0 0 0 3px rgba(56,214,245,0.55), 0 3px 10px rgba(22,33,62,0.2); }
.ob-b-name { margin-top: 3px; padding: 1px 6px; border-radius: 6px; background: rgba(22,33,62,0.82); color: #fff; font: 600 10px/14px "IBM Plex Sans", sans-serif;
  white-space: nowrap; display: none; }
.ob-bubble[data-selected="1"] .ob-b-name, .ob-bubble[data-label="1"] .ob-b-name { display: block; }
.ob-b-empty .ob-b-pill, .ob-b-empty .ob-b-tail { display: none; }
.ob-b-card { position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%); min-width: 170px; max-width: 230px; padding: 8px 10px;
  border-radius: 8px; background: rgba(253,252,249,0.97); border: 1px solid #d9d4c7; box-shadow: 0 8px 24px rgba(22,33,62,0.18); color: #16213e;
  font: 400 11px/1.45 "IBM Plex Sans", sans-serif; display: none; text-align: left; }
.ob-bubble:hover .ob-b-card { display: block; }
.ob-b-card b { font-weight: 600; font-size: 12px; }
.ob-b-card .ob-c-role { color: #62697c; }
.ob-b-card .ob-c-bar { height: 4px; border-radius: 2px; background: #e5e7eb; margin-top: 5px; overflow: hidden; }
.ob-b-card .ob-c-bar i { display: block; height: 100%; background: #2563eb; }
.ob-zone { position: absolute; pointer-events: none; display: flex; align-items: center; gap: 6px; padding: 3px 9px 3px 4px; border-radius: 999px;
  background: rgba(255,255,255,0.92); border: 1px solid #c9d7ec; box-shadow: 0 2px 8px rgba(22,33,62,0.12); color: #16213e;
  font: 600 11px/1 "IBM Plex Sans", sans-serif; white-space: nowrap; }
.ob-zone i { display: inline-flex; align-items: center; justify-content: center; width: 17px; height: 17px; border-radius: 50%; background: #1d4ed8;
  color: #fff; font-style: normal; font-size: 10px; }
.ob-zone small { font-weight: 400; color: #62697c; }
.ob-zones-off .ob-zone { display: none; }
.ob-bubbles-hidden .ob-bubble { display: none; }
@keyframes ob-pop { 0% { transform: translateY(var(--lift, 0px)) scale(calc(var(--s, 1) * 0.6)); opacity: 0.2; } 100% { transform: translateY(var(--lift, 0px)) scale(var(--s, 1)); opacity: 1; } }
@keyframes ob-zzz { 0%, 100% { transform: translateY(0); opacity: 0.85; } 50% { transform: translateY(-2px); opacity: 1; } }
`;

interface Bubble {
  id: AgentId;
  el: HTMLDivElement;
  pill: HTMLDivElement;
  name: HTMLDivElement;
  card: HTMLDivElement;
  obj: CSS2DObject;
  status: AgentStatus | null;
  cardKey: string;
  screen: { x: number; y: number; prio: number; visible: boolean };
}

/**
 * Status bubbles: small HTML/CSS bubbles projected above each Openling's head
 * (CSS2DRenderer). One primary bubble per agent, a hover card, click to select. Bubbles
 * behind solid walls hide; at distance they shrink; nearby bubbles stack instead of overlapping.
 */
export class StatusBubbles {
  readonly renderer = new CSS2DRenderer();
  private readonly scene = new Scene();
  private readonly bubbles = new Map<AgentId, Bubble>();
  private readonly walls: OfficeWall[];
  private readonly styleEl: HTMLStyleElement;
  private visible = true;
  private readonly onSelect: (id: AgentId) => void;
  private readonly tmp = new Vector3();
  private readonly cam = new Vector3();
  private size = { w: 1, h: 1 };
  private occlusionClock = 0;

  constructor(container: HTMLElement, walls: OfficeWall[], onSelect: (id: AgentId) => void) {
    this.walls = walls.filter((w) => w.kind === "solid" || w.kind === "low" || w.kind === "partition");
    this.onSelect = onSelect;
    this.styleEl = document.createElement("style");
    this.styleEl.textContent = STYLE;
    document.head.appendChild(this.styleEl);
    const el = this.renderer.domElement;
    el.className = "ob-bubbles";
    container.appendChild(el);
  }

  add(id: AgentId, name: string) {
    const el = document.createElement("div");
    el.className = "ob-bubble";
    el.dataset.agent = id;
    el.innerHTML = '<div class="ob-b-inner"><div class="ob-b-card"></div><div class="ob-b-pill"></div><div class="ob-b-tail"></div><div class="ob-b-name"></div></div>';
    const pill = el.querySelector(".ob-b-pill") as HTMLDivElement;
    const card = el.querySelector(".ob-b-card") as HTMLDivElement;
    const nameEl = el.querySelector(".ob-b-name") as HTMLDivElement;
    nameEl.textContent = name;
    el.addEventListener("pointerdown", (e) => { e.stopPropagation(); });
    el.addEventListener("click", (e) => { e.stopPropagation(); this.onSelect(id); });
    const obj = new CSS2DObject(el);
    obj.center.set(0.5, 1);
    this.scene.add(obj);
    this.bubbles.set(id, { id, el, pill, name: nameEl, card, obj, status: null, cardKey: "", screen: { x: 0, y: 0, prio: 0, visible: false } });
  }

  /** Numbered zone labels (UI callouts, not geometry), like the approved design's legend. */
  addZoneLabel(number: number, label: string, tagline: string, x: number, y: number, z: number) {
    const el = document.createElement("div");
    el.className = "ob-zone";
    el.innerHTML = `<i>${number}</i>${esc(label)}${tagline ? ` <small>${esc(tagline)}</small>` : ""}`;
    const obj = new CSS2DObject(el);
    obj.position.set(x, y, z);
    obj.center.set(0.5, 1);
    this.scene.add(obj);
  }

  setZoneLabels(on: boolean) {
    this.renderer.domElement.classList.toggle("ob-zones-off", !on);
  }

  setVisible(on: boolean) {
    this.visible = on;
    this.renderer.domElement.classList.toggle("ob-bubbles-hidden", !on);
  }

  setSelected(id: AgentId | null) {
    for (const b of this.bubbles.values()) b.el.dataset.selected = b.id === id ? "1" : "0";
  }

  setSize(w: number, h: number) {
    this.size = { w, h };
    this.renderer.setSize(w, h);
  }

  /** Updates one bubble's content and anchor (head position, world space). */
  update(info: BubbleInfo, head: Vector3) {
    const b = this.bubbles.get(info.id);
    if (!b) return;
    b.obj.position.set(head.x, head.y + 0.16, head.z);
    if (b.status !== info.status) {
      const bubble = bubbleFor(info.status);
      b.status = info.status;
      if (bubble) {
        b.pill.innerHTML = ICONS[bubble.icon];
        b.el.dataset.tone = bubble.tone;
        b.el.dataset.icon = bubble.icon;
        b.el.classList.remove("ob-b-empty");
        b.el.dataset.pop = "0";
        void b.el.offsetWidth;
        b.el.dataset.pop = "1";
      } else {
        b.pill.innerHTML = "";
        b.el.dataset.tone = "calm";
        b.el.dataset.icon = "";
        b.el.classList.add("ob-b-empty");
      }
      b.el.setAttribute("aria-label", `${info.name}: ${STATUS[info.status].label}`);
    }
    const cardKey = `${info.status}|${info.detail}|${info.task}|${info.progress === null ? "" : Math.round(info.progress * 20)}`;
    if (cardKey !== b.cardKey) {
      b.cardKey = cardKey;
      const pct = info.progress === null ? "" : `<div class="ob-c-bar"><i style="width:${Math.round(info.progress * 100)}%"></i></div>`;
      b.card.innerHTML = `<b>${esc(info.name)}</b> <span class="ob-c-role">· ${esc(info.role)}</span><br>${esc(info.detail || STATUS[info.status].label)}`
        + (info.task ? `<br><span class="ob-c-role">${esc(info.task)}</span>` : "") + pct;
    }
  }

  render(camera: PerspectiveCamera, dt: number) {
    camera.getWorldPosition(this.cam);
    this.occlusionClock -= dt;
    const checkOcclusion = this.occlusionClock <= 0;
    if (checkOcclusion) this.occlusionClock = 0.15;
    const list = [...this.bubbles.values()];
    for (const b of list) {
      const p = b.obj.position;
      const dist = this.cam.distanceTo(p);
      const s = Math.max(0.62, Math.min(1.15, 14 / dist));
      b.el.style.setProperty("--s", s.toFixed(3));
      if (checkOcclusion) b.el.dataset.hidden = this.occluded(this.cam, p) ? "1" : "0";
      this.tmp.copy(p).project(camera);
      b.screen = {
        x: (this.tmp.x * 0.5 + 0.5) * this.size.w, y: (-this.tmp.y * 0.5 + 0.5) * this.size.h,
        prio: b.status ? STATUS[b.status].priority : 0,
        visible: this.visible && this.tmp.z < 1 && !b.el.classList.contains("ob-b-empty") && b.el.dataset.hidden !== "1",
      };
    }
    // stack bubbles that would overlap on screen (the lower priority one lifts)
    const lift = new Map<AgentId, number>();
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const a = list[i].screen, c = list[j].screen;
        if (!a.visible || !c.visible) continue;
        if (Math.abs(a.x - c.x) < 34 && Math.abs(a.y - c.y) < 34) {
          const loser = a.prio >= c.prio ? list[j] : list[i];
          lift.set(loser.id, (lift.get(loser.id) ?? 0) - 32);
        }
      }
    }
    for (const b of list) b.el.style.setProperty("--lift", `${lift.get(b.id) ?? 0}px`);
    this.renderer.render(this.scene, camera);
  }

  /** True when a solid wall stands between the camera and the point. */
  private occluded(cam: Vector3, p: Vector3): boolean {
    for (const w of this.walls) {
      const [ax, az] = w.from, [bx, bz] = w.to;
      // intersection of the camera->point segment with the wall's vertical plane
      const ex = bx - ax, ez = bz - az;
      const dx = p.x - cam.x, dz = p.z - cam.z;
      const den = dx * ez - dz * ex;
      if (Math.abs(den) < 1e-9) continue;
      const t = ((ax - cam.x) * ez - (az - cam.z) * ex) / den;
      const u = ((ax - cam.x) * dz - (az - cam.z) * dx) / den;
      if (t <= 0.001 || t >= 0.999 || u < 0 || u > 1) continue;
      const y = cam.y + (p.y - cam.y) * t;
      const solidTop = w.kind === "partition" ? 0.42 : w.height;
      if (y >= solidTop) continue;
      const along = u * Math.hypot(ex, ez);
      if (w.openings.some(([t0, t1]) => along >= t0 && along <= t1)) continue;
      return true;
    }
    return false;
  }

  dispose() {
    for (const b of this.bubbles.values()) b.obj.removeFromParent();
    this.renderer.domElement.remove();
    this.styleEl.remove();
  }
}

function esc(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}
