import {
  Color, HalfFloatType, Mesh, MeshBasicMaterial, NeutralToneMapping, PerspectiveCamera, Quaternion, Raycaster, RingGeometry, Scene, SRGBColorSpace,
  Vector2, Vector3, VSMShadowMap, WebGLRenderTarget, WebGLRenderer, type Object3D,
} from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { GTAOPass } from "three/addons/postprocessing/GTAOPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { AGENTS, type AgentId } from "../../lib/office/agents";
import type { MessageCheck } from "../../lib/office/conversation";
import { LayoutIndex, OFFICE_GLB_URLS, OFFICE_LAYOUT, yawTo, type Vec2 } from "../../lib/office/layout";
import { NavGraph, obstacleDist } from "../../lib/office/nav";
import { OfficeSimulation, STEP, type AssignResult, type ChatMessage, type MockAgentTask } from "../../lib/office/simulation";
import { STATUS, type AgentStatus } from "../../lib/office/status";
import { ANIMATED_OPENLING_URL, OPENLING_PROPS_URL, gltfByteLength, loadGltf, releaseGpuResources } from "../openlings/viewer/loadOpenling";
import { OpenlingCharacter } from "../openlings/runtime/OpenlingCharacter";
import { PropLibrary } from "../openlings/runtime/PropLibrary";
import { AgentActor, type AgentInteraction, type GreetingPhase } from "./runtime/AgentActor";
import { CameraRig } from "./runtime/CameraRig";
import { Globe } from "./runtime/Globe";
import { buildOfficeScene, type OfficeScene } from "./runtime/officeAssets";
import { OFFICE_LIGHTING, OfficeLighting, scaleLeds, type OfficeLightingId } from "./runtime/officeLighting";
import { ScreenPainter, type ScreenData } from "./runtime/ScreenPainter";
import { StatusBubbles } from "./runtime/StatusBubbles";

export type OfficeQuality = "high" | "balanced" | "reduced";
const QUALITY: Record<OfficeQuality, { pixelRatio: number; shadow: number; ao: boolean; bloom: boolean; slowScreens: boolean }> = {
  high: { pixelRatio: 2, shadow: 4096, ao: true, bloom: true, slowScreens: false },
  balanced: { pixelRatio: 1.5, shadow: 2048, ao: true, bloom: true, slowScreens: false },
  reduced: { pixelRatio: 1, shadow: 1024, ao: false, bloom: false, slowScreens: true },
};
const MAX_STEPS_PER_FRAME = 40;
/** Free floor around a standing Openling for it to turn toward the viewer in place: body only, or with held props. */
const ROOM_TO_TURN = 0.29;
const ROOM_TO_TURN_PROPS = 0.36;
/** Greeting close-up: vertical fov, and the share of the free view height the Openling fills. */
const CLOSEUP_FOV = 32;
const CLOSEUP_FILL = 0.46;

export interface AgentRow {
  id: AgentId;
  name: string;
  role: string;
  status: AgentStatus;
  statusLabel: string;
  detail: string;
  tone: string;
  zone: string;
  task: string | null;
  progress: number | null;
  recent: { t: number; text: string }[];
  walking: boolean;
  activity: string;
}

/** The selected agent's chat, as the conversation panel shows it. */
export interface ChatView {
  agent: AgentId;
  name: string;
  role: string;
  status: AgentStatus;
  statusLabel: string;
  detail: string;
  tone: string;
  messages: ChatMessage[];
  tasks: MockAgentTask[];
  interaction: AgentInteraction;
  greetingPhase: GreetingPhase | null;
}

export interface OfficeSnapshot {
  t: number;
  running: boolean;
  speed: number;
  phase: string;
  agents: AgentRow[];
  task: ScreenData["task"];
  completed: number;
  inProgress: number;
  active: number;
  alerts: string[];
  log: { t: number; text: string; agent?: AgentId }[];
  selected: AgentId | null;
  /** Counts selections (also of the agent already selected), so the page can reopen its chat. */
  selectSeq: number;
  following: boolean;
  chat: ChatView | null;
}

export interface OfficeLoadStats {
  loadMs: number;
  bytes: number;
  officeTriangles: number;
  batches: number;
  meshesIn: number;
  screens: number;
  agents: number;
}

export interface OfficeViewerOptions {
  onProgress?: (fraction: number) => void;
  onReady?: (stats: OfficeLoadStats) => void;
  onError?: (error: Error) => void;
  onSnapshot?: (s: OfficeSnapshot) => void;
  workers?: boolean;
}

/**
 * The Living Office: the office GLBs, the shared animated Openling and its props, the mock
 * simulation and everything that turns it into a living scene (actors, status bubbles,
 * screens, globe, robot arm), plus camera, lighting, quality and selection.
 */
export class OfficeViewer {
  private readonly renderer: WebGLRenderer;
  private readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(30, 1, 0.05, 120);
  /** GTAO sees only layer 0: glass, holograms and overlays (layer 1) must not occlude. */
  private readonly aoCamera = new PerspectiveCamera(30, 1, 0.05, 120);
  private readonly composer: EffectComposer;
  private readonly ao: GTAOPass;
  private readonly bloom: UnrealBloomPass;
  private readonly lighting: OfficeLighting;
  readonly rig: CameraRig;
  private readonly bubbles: StatusBubbles;
  private readonly index = new LayoutIndex(OFFICE_LAYOUT);
  private readonly nav = new NavGraph(this.index);
  private readonly container: HTMLElement;
  private readonly options: OfficeViewerOptions;
  private readonly resizeObserver: ResizeObserver;
  private office: OfficeScene | null = null;
  private painter: ScreenPainter | null = null;
  private globe: Globe | null = null;
  private characterGltf: Awaited<ReturnType<typeof loadGltf>> | null = null;
  private props: PropLibrary | null = null;
  sim: OfficeSimulation | null = null;
  readonly actors = new Map<AgentId, AgentActor>();
  private readonly jointBase = new Map<Object3D, Quaternion>();
  private readonly selectionRing: Mesh;
  private selected: AgentId | null = null;
  private running = true;
  private speed = 1;
  private accumulator = 0;
  private lastFrame = -1;
  private needsRender = true;
  private snapshotClock = 0;
  private disposed = false;
  private quality: OfficeQuality = "high";
  private lightingId: OfficeLightingId = "day";
  private benchmarkFrames: number[] | null = null;
  private readonly raycaster = new Raycaster();
  private readonly pointerDown = new Vector2();
  private readonly gestureSeen = new Map<AgentId, number>();
  private robotTime = 0;
  /** View pixels covered by the chat panel (right on wide screens, bottom on phones). */
  private insets = { right: 0, bottom: 0 };
  private selectSeq = 0;
  /** Solid height of every obstacle (walls: their opaque part; glass sees through), for camera line of sight. */
  private readonly obstacleTop = obstacleHeights();
  /** Plant foliage reaches far past the pot footprint: canopies block the view too. */
  private readonly canopies = plantCanopies();

  constructor(container: HTMLElement, options: OfficeViewerOptions = {}) {
    this.container = container;
    this.options = options;
    this.renderer = new WebGLRenderer({ antialias: false, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, QUALITY.high.pixelRatio));
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.toneMapping = NeutralToneMapping;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = VSMShadowMap;
    this.renderer.info.autoReset = false;
    const canvas = this.renderer.domElement;
    canvas.style.display = "block";
    canvas.style.width = canvas.style.height = "100%";
    canvas.style.touchAction = "none";
    container.appendChild(canvas);

    const target = new WebGLRenderTarget(1, 1, { type: HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(this.renderer, target);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.camera.layers.enable(FX_LAYER);
    this.ao = new GTAOPass(this.scene, this.aoCamera, 1, 1);
    this.ao.updateGtaoMaterial({ radius: 0.32, distanceExponent: 1.4, thickness: 1.2, scale: 1, samples: 12 });
    this.ao.blendIntensity = 0.75;
    this.composer.addPass(this.ao);
    this.bloom = new UnrealBloomPass(new Vector2(1, 1), 0.3, 0.18, 3.6);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    this.lighting = new OfficeLighting(this.renderer, OFFICE_LAYOUT.lights, OFFICE_LAYOUT.architecture.bounds);
    this.scene.add(this.lighting.group);
    this.scene.environment = this.lighting.environment;

    this.selectionRing = new Mesh(new RingGeometry(0.36, 0.43, 48), new MeshBasicMaterial({ color: new Color("#38d6f5"), transparent: true, opacity: 0.85, depthWrite: false }));
    this.selectionRing.rotation.x = -Math.PI / 2;
    this.selectionRing.position.y = 0.012;
    this.selectionRing.visible = false;
    this.selectionRing.renderOrder = 5;
    this.selectionRing.layers.set(FX_LAYER);
    this.scene.add(this.selectionRing);

    this.rig = new CameraRig(this.camera, canvas, OFFICE_LAYOUT.architecture.bounds, this.invalidate);
    this.bubbles = new StatusBubbles(container, OFFICE_LAYOUT.walls, (id) => this.select(id, true));
    for (const z of OFFICE_LAYOUT.zones) {
      const focus = this.index.camera(z.id);
      const [x, y, zz] = focus ? focus.target : [z.center[0], 0, z.center[1]];
      this.bubbles.addZoneLabel(z.number, z.label, "", x, Math.max(1.55, y + 1.2), zz);
    }
    this.view("main", false);
    this.setLighting("day");
    this.setQuality("high");

    canvas.addEventListener("pointerdown", this.onPointerDown);
    canvas.addEventListener("pointerup", this.onPointerUp);
    canvas.addEventListener("pointermove", this.onPointerMove);
    this.resizeObserver = new ResizeObserver(this.resize);
    this.resizeObserver.observe(container);
    this.resize();
    this.renderer.setAnimationLoop(this.tick);
    void this.load();
  }

  // ------------------------------------------------------------------ loading
  private async load() {
    const started = performance.now();
    const urls = [...OFFICE_GLB_URLS, ANIMATED_OPENLING_URL, OPENLING_PROPS_URL];
    const progress = new Map<string, number>();
    const report = () => this.options.onProgress?.([...progress.values()].reduce((a, b) => a + b, 0) / urls.length);
    try {
      const gltfs = await Promise.all(urls.map((u) => loadGltf(u, (f) => { progress.set(u, f); report(); })));
      if (this.disposed) return;
      const officeGltfs = gltfs.slice(0, OFFICE_GLB_URLS.length);
      this.characterGltf = gltfs[OFFICE_GLB_URLS.length];
      this.props = new PropLibrary(gltfs[OFFICE_GLB_URLS.length + 1]);
      const maxAniso = this.renderer.capabilities.getMaxAnisotropy();
      this.office = buildOfficeScene(officeGltfs, OFFICE_LAYOUT, maxAniso);
      this.scene.add(this.office.root);
      scaleLeds(this.office.materials.values(), OFFICE_LIGHTING[this.lightingId].led);
      for (const [, j] of this.office.joints) this.jointBase.set(j, j.quaternion.clone());
      const globeItem = this.index.item("Command_Globe");
      this.globe = new Globe(Number(globeItem.params.radius ?? 0.36));
      this.globe.place(globeItem.position[0], Number(globeItem.params.globeY ?? 1.7), globeItem.position[2]);
      this.scene.add(this.globe.group);
      this.globe.group.traverse((o) => o.layers.set(FX_LAYER));
      this.office.root.traverse((o) => {
        const m = (o as Mesh).material as { transparent?: boolean } | undefined;
        if ((o as Mesh).isMesh && m?.transparent) o.layers.set(FX_LAYER);
      });
      await document.fonts?.ready;
      if (this.disposed) return;
      this.painter = new ScreenPainter(this.office, maxAniso);
      this.painter.setSlow(QUALITY[this.quality].slowScreens);
      this.painter.paintSigns();
      this.startSimulation();
      this.painter.update(this.screenData(), 0, true);
      this.render();
      const bytes = urls.reduce((a, u) => a + (gltfByteLength(u) ?? 0), 0);
      this.options.onReady?.({
        loadMs: Math.round(performance.now() - started), bytes, officeTriangles: this.office.stats.triangles, batches: this.office.stats.batches,
        meshesIn: this.office.stats.meshesIn, screens: this.painter.count.screens, agents: this.actors.size,
      });
      this.emitSnapshot();
    } catch (error) {
      if (!this.disposed) this.options.onError?.(error instanceof Error ? error : new Error(String(error)));
    }
  }

  /** (Re)creates the simulation and the Openlings at their start anchors. */
  private startSimulation() {
    if (!this.characterGltf || !this.office) return;
    for (const a of this.actors.values()) a.dispose();
    this.actors.clear();
    this.gestureSeen.clear();
    // chairs and stools back to their rest poses
    for (const it of OFFICE_LAYOUT.items) {
      const o = this.office.dynamic.get(it.id);
      if (o && it.params.restPose) {
        o.position.set(it.params.restPose[0], 0, it.params.restPose[2]);
        o.rotation.set(0, it.params.restYaw ?? 0, 0);
      }
    }
    const sim: OfficeSimulation = new OfficeSimulation({
      atGoal: (id) => this.actors.get(id)?.atGoalFor(sim.state.agents[id].goal) ?? true,
    }, { workers: this.options.workers !== false });
    this.sim = sim;
    const world = { index: this.index, nav: this.nav, dynamic: this.office.dynamic, actors: () => [...this.actors.values()] };
    const maxAniso = this.renderer.capabilities.getMaxAnisotropy();
    for (const id of sim.agentIds) {
      const profile = AGENTS.find((a) => a.id === id)!;
      const character = new OpenlingCharacter(this.characterGltf, this.props, { seed: profile.seed, maxAnisotropy: maxAniso });
      const actor = new AgentActor(id, character, world);
      actor.setStatus(sim.state.agents[id].status);
      this.actors.set(id, actor);
      this.scene.add(character.root);
      if (!this.bubbleIds.has(id)) {
        this.bubbles.add(id, profile.name);
        this.bubbleIds.add(id);
      }
      this.gestureSeen.set(id, sim.state.agents[id].gestureSeq);
    }
    this.accumulator = 0;
    this.robotTime = 0;
    this.needsRender = true;
  }
  private readonly bubbleIds = new Set<AgentId>();

  // ------------------------------------------------------------------ public controls
  play() { this.running = true; this.emitSnapshot(); }
  pause() { this.running = false; this.emitSnapshot(); }
  setSpeed(k: number) { this.speed = k; this.emitSnapshot(); }
  reset() {
    this.startSimulation();
    if (this.painter) this.painter.update(this.screenData(), 0, true);
    this.select(null);
    this.emitSnapshot();
  }
  triggerBlocked() { this.sim?.triggerBlocked(); this.emitSnapshot(); }
  triggerComplete() { this.sim?.triggerComplete(); this.emitSnapshot(); }
  triggerReport() { this.sim?.triggerReport(); this.emitSnapshot(); }
  setBubbles(on: boolean) { this.bubbles.setVisible(on); this.invalidate(); }
  setZoneLabels(on: boolean) { this.bubbles.setZoneLabels(on); this.invalidate(); }

  setLighting(id: OfficeLightingId) {
    this.lightingId = id;
    const p = OFFICE_LIGHTING[id];
    this.lighting.apply(p);
    this.scene.background = this.lighting.backdrop;
    this.scene.environmentIntensity = p.environmentIntensity;
    this.renderer.toneMappingExposure = p.exposure;
    this.bloom.strength = p.bloom.strength;
    this.bloom.radius = p.bloom.radius;
    this.bloom.threshold = p.bloom.threshold;
    if (this.office) scaleLeds(this.office.materials.values(), p.led);
    this.invalidate();
  }

  setQuality(q: OfficeQuality) {
    this.quality = q;
    const c = QUALITY[q];
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, c.pixelRatio));
    this.lighting.setShadowMapSize(c.shadow);
    this.ao.enabled = c.ao;
    this.bloom.enabled = c.bloom;
    this.painter?.setSlow(c.slowScreens);
    this.resize();
  }

  /** Camera preset by id (layout cameras: main, front, top, left, right and one per zone). */
  view(id: string, animate = true) {
    const c = this.index.camera(id);
    if (!c) return;
    this.lastView = id;
    // overviews keep their direction and fit the whole building to the current viewport
    if (c.zone) this.rig.go(c, animate);
    else {
      const position = this.fitOverview(c);
      this.rig.go({ ...c, position, target: this.fitTarget ?? c.target }, animate);
    }
    this.emitSnapshot();
  }

  /**
   * Distance along the preset direction (and a small vertical recentring) at which the whole
   * building fills the current viewport: tall rear walls, low front walls, the porch.
   */
  private fitOverview(c: { position: [number, number, number]; target: [number, number, number]; fov: number }): [number, number, number] {
    const [x0, z0, x1, z1] = OFFICE_LAYOUT.architecture.bounds;
    const corners: Vector3[] = [];
    for (const x of [x0 - 0.15, x1 + 0.15]) {
      corners.push(new Vector3(x, 0, z0 - 0.15), new Vector3(x, 2.65, z0 - 0.15), new Vector3(x, 0, 4.75), new Vector3(x, 0.8, 4.75));
    }
    corners.push(new Vector3(-2.6, 0, z1 + 0.1), new Vector3(2.6, 0, z1 + 0.1), new Vector3(-2.6, 0.5, z1), new Vector3(2.6, 0.5, z1));
    const target = new Vector3(...c.target);
    const dir = new Vector3(...c.position).sub(target).normalize();
    const cam = this.camera.clone();
    cam.clearViewOffset();
    cam.fov = c.fov;
    cam.aspect = this.camera.aspect || 1.6;
    const place = (d: number) => {
      cam.position.copy(target).addScaledVector(dir, d);
      cam.up.set(0, 1, 0);
      if (Math.abs(dir.y) > 0.98) cam.up.set(0, 0, -1);
      cam.lookAt(target);
      cam.updateProjectionMatrix();
      cam.updateMatrixWorld(true);
    };
    const extent = () => {
      let ymin = Infinity, ymax = -Infinity, xmax = 0, behind = false;
      for (const p of corners) {
        const q = p.clone().project(cam);
        ymin = Math.min(ymin, q.y);
        ymax = Math.max(ymax, q.y);
        xmax = Math.max(xmax, Math.abs(q.x));
        if (q.z >= 1) behind = true;
      }
      return { ymin, ymax, xmax, behind };
    };
    let d = 30;
    for (let pass = 0; pass < 3; pass++) {
      let lo = 3, hi = 90;
      for (let i = 0; i < 30; i++) {
        const mid = (lo + hi) / 2;
        place(mid);
        const e = extent();
        if (!e.behind && e.xmax <= 0.985 && e.ymax - e.ymin <= 1.9) hi = mid; else lo = mid;
      }
      d = hi;
      place(d);
      const e = extent();
      // recentre vertically: move the target along the camera's up axis
      const shift = ((e.ymax + e.ymin) / 2) * Math.tan((cam.fov * Math.PI) / 360) * d;
      const up = new Vector3(0, 1, 0).applyQuaternion(cam.quaternion);
      target.addScaledVector(up, shift);
    }
    place(d);
    this.fitTarget = target.toArray() as [number, number, number];
    return cam.position.toArray() as [number, number, number];
  }
  private fitTarget: [number, number, number] | null = null;

  /**
   * Selects an Openling. A new selection (`focus`) frames it in a close-up and it greets the viewer
   * once; selecting it again only re-frames it (no repeated wave). Its chat greets the first time.
   */
  select(id: AgentId | null, focus = false) {
    const fresh = id !== this.selected;
    this.selected = id;
    if (id) this.selectSeq++;
    this.bubbles.setSelected(id);
    this.selectionRing.visible = !!id;
    if (!id) this.rig.setFollow(null);
    if (id) this.sim?.openChat(id);
    if (id && focus) this.frameAgent(id, fresh);
    this.emitSnapshot();
    this.invalidate();
  }

  /** Replays the greeting on request ("Say hi"); no-op while paused or already greeting. */
  sayHi(id: AgentId) {
    if (this.selected !== id) return;
    this.frameAgent(id, true);
    this.emitSnapshot();
  }

  focusAgent(id: AgentId, follow: boolean) {
    const a = this.actors.get(id);
    if (!a) return;
    this.frameAgent(id, false);
    if (follow) this.followAgent(id);
    this.emitSnapshot();
  }

  private followAgent(id: AgentId) {
    this.rig.setFollow(() => {
      const a = this.actors.get(id);
      return a ? new Vector3(a.pos[0], 0, a.pos[1]) : this.rig.controls.target.clone();
    });
  }

  /** Pixels of the view the chat panel covers; close-ups keep the Openling in the rest. */
  setViewInsets(right: number, bottom: number) {
    this.insets = { right: Math.max(0, right), bottom: Math.max(0, bottom) };
  }

  /**
   * Close-up of an Openling with its face visible and nothing solid in between. One that can turn
   * (standing with room around it, or paused on a route) is seen from near the current view and turns
   * to it; a seated one, or one standing at tight furniture, is seen from in front instead.
   */
  private frameAgent(id: AgentId, greet: boolean) {
    const a = this.actors.get(id);
    if (!a) return;
    const room = a.holdsProps ? ROOM_TO_TURN_PROPS : ROOM_TO_TURN;
    const turnable = !a.seated && (a.onRoute || a.isWalking || this.nav.freeRadius(a.pos) >= room);
    const shot = this.closeup(a, turnable);
    this.rig.go(shot);
    // a walking Openling keeps going until it can stop safely: the camera follows it so it stays in view
    if (a.isWalking) this.followAgent(id);
    if (greet && this.running) {
      const face = turnable ? yawTo(a.pos[0], a.pos[1], shot.eye[0], shot.eye[2]) : null;
      a.greet(face);
    }
  }

  private closeup(a: AgentActor, turnable: boolean): { position: [number, number, number]; target: [number, number, number]; fov: number; shift: [number, number]; eye: [number, number, number] } {
    const { clientWidth: w, clientHeight: h } = this.container;
    const right = Math.min(this.insets.right, w * 0.6), bottom = Math.min(this.insets.bottom, h * 0.7);
    const tanHalf = Math.tan((CLOSEUP_FOV * Math.PI) / 360);
    const freeShare = Math.max(0.3, (h - bottom) / Math.max(1, h));
    const dist = Math.min(6, Math.max(2.3, (0.96 / (CLOSEUP_FILL * freeShare)) / (2 * tanHalf)));
    const center = new Vector3(a.pos[0], 0.5, a.pos[1]);
    const view = this.camera.position.clone().sub(this.rig.controls.target);
    const viewYaw = Math.atan2(view.x, view.z);
    const base = turnable ? viewYaw : a.yaw;
    // head and body must be in sight (a seated Openling's lap may hide behind its desk)
    const probes = (a.seated ? [0.3, 0.1] : [0.3, -0.15]).map((dy) => center.clone().add(new Vector3(0, dy, 0)));
    // views ranked by how far they turn from the preferred direction and how steeply they look down
    const views: { off: number; elev: number; cost: number }[] = [];
    for (const elev of [17, 28, 40, 55]) {
      for (const off of [0, 25, -25, 50, -50, 75, -75, 100, -100, 130, -130, 180]) {
        if (!turnable && Math.abs(off) > 100) continue; // keep the face in view
        views.push({ off, elev, cost: Math.abs(off) / 25 + (elev - 17) / 12 + (off < 0 ? 0.01 : 0) });
      }
    }
    views.sort((p, q) => p.cost - q.cost);
    let eye: Vector3 | null = null;
    for (const { off, elev } of views) {
      const yaw = base + (off * Math.PI) / 180;
      const e = (elev * Math.PI) / 180;
      const p = center.clone().add(new Vector3(Math.sin(yaw) * Math.cos(e), Math.sin(e), Math.cos(yaw) * Math.cos(e)).multiplyScalar(dist));
      if (probes.every((q) => this.lineOfSight(q, p, a))) { eye = p; break; }
    }
    eye ??= center.clone().add(new Vector3(Math.sin(base) * 0.5, 0.87, Math.cos(base) * 0.5).normalize().multiplyScalar(dist));
    return {
      position: eye.toArray() as [number, number, number],
      target: center.toArray() as [number, number, number],
      fov: CLOSEUP_FOV,
      // the Openling sits in the middle of the part of the view the chat panel leaves free
      shift: [-right / Math.max(1, w), bottom / Math.max(1, h)],
      eye: eye.toArray() as [number, number, number],
    };
  }

  /** No wall's opaque part, furniture, foliage or other Openling between two points (glass counts as see-through). */
  private lineOfSight(a: Vector3, b: Vector3, self?: AgentActor): boolean {
    const n = Math.ceil(a.distanceTo(b) / 0.06);
    const p = new Vector3();
    for (let i = 3; i <= n; i++) {
      p.lerpVectors(a, b, i / n);
      const q: Vec2 = [p.x, p.z];
      for (const o of OFFICE_LAYOUT.obstacles) {
        if (p.y > (this.obstacleTop.get(o.id) ?? 0.8)) continue;
        if (obstacleDist(o, q, q) < 0.02) return false;
      }
      for (const c of this.canopies) {
        if (p.y >= c.y0 && p.y <= c.y1 && Math.hypot(p.x - c.x, p.z - c.z) < c.r) return false;
      }
      for (const o of this.actors.values()) {
        if (o !== self && p.y < 0.98 && Math.hypot(p.x - o.pos[0], p.z - o.pos[1]) < 0.32) return false;
      }
    }
    return true;
  }

  // ------------------------------------------------------------------ chat (local mock: nothing leaves the browser)
  sendMessage(id: AgentId, text: string): MessageCheck | null {
    const r = this.sim?.sendMessage(id, text) ?? null;
    this.emitSnapshot();
    return r;
  }

  answerProposal(id: AgentId, messageId: string, action: "assign" | "replace" | "dismiss"): boolean {
    const r = this.sim?.answerProposal(id, messageId, action) ?? false;
    if (r && action !== "dismiss") this.keepInView(id);
    this.emitSnapshot();
    return r;
  }

  quickTask(id: AgentId, quickId: string): AssignResult | null {
    const r = this.sim?.quickTask(id, quickId) ?? null;
    if (r?.ok) this.keepInView(id);
    this.emitSnapshot();
    return r;
  }

  /** The selected Openling is about to set off for its task: the camera follows it (until another view is chosen). */
  private keepInView(id: AgentId) {
    if (this.selected === id && !this.rig.following) this.followAgent(id);
  }

  stopFollow() { this.rig.setFollow(null); this.emitSnapshot(); }

  // ------------------------------------------------------------------ frame
  private readonly invalidate = () => { this.needsRender = true; };

  private readonly tick = (now: number) => {
    const realDt = this.lastFrame < 0 ? 0 : Math.min(0.1, (now - this.lastFrame) / 1000);
    this.lastFrame = now;
    const sim = this.sim;
    let simDt = 0;
    if (sim && this.running) {
      this.accumulator += realDt * this.speed;
      let n = 0;
      while (this.accumulator >= STEP && n < MAX_STEPS_PER_FRAME) {
        for (const a of this.actors.values()) a.step(STEP);
        sim.step();
        this.syncFromSimulation();
        this.accumulator -= STEP;
        n++;
      }
      if (n === MAX_STEPS_PER_FRAME) this.accumulator = 0;
      simDt = n * STEP;
    }
    if (simDt > 0 || !this.running) {
      for (const a of this.actors.values()) a.frame(simDt);
    }
    if (simDt > 0) {
      this.globe?.update(simDt);
      this.animateRobot(simDt);
      this.needsRender = true;
    }
    if (this.painter && sim && simDt > 0) this.painter.update(this.screenData(), sim.t);
    if (this.rig.update(realDt)) this.needsRender = true;
    const sel = this.selected ? this.actors.get(this.selected) : null;
    if (sel) {
      this.selectionRing.position.set(sel.pos[0], 0.012, sel.pos[1]);
      (this.selectionRing.material as MeshBasicMaterial).opacity = 0.65 + 0.2 * Math.sin(now / 300);
    }
    this.snapshotClock -= realDt;
    if (this.snapshotClock <= 0) {
      this.snapshotClock = 0.2;
      this.emitSnapshot();
    }
    if (this.benchmarkFrames) this.benchmarkFrames.push(now);
    else if (!this.needsRender) return;
    this.needsRender = false;
    this.render(realDt);
  };

  /** Goals, statuses and gestures flow from the simulation state to the actors. */
  private syncFromSimulation() {
    const sim = this.sim!;
    for (const [id, actor] of this.actors) {
      const st = sim.state.agents[id];
      actor.setGoal(st.goal);
      if (actor.status !== st.status) actor.setStatus(st.status);
      if (this.gestureSeen.get(id) !== st.gestureSeq) {
        this.gestureSeen.set(id, st.gestureSeq);
        if (st.gesture === "wave") actor.wave();
      }
    }
  }

  private animateRobot(dt: number) {
    if (!this.office) return;
    this.robotTime += dt;
    const t = this.robotTime;
    const q = new Quaternion();
    for (const [name, j] of this.office.joints) {
      const base = this.jointBase.get(j)!;
      const n = Number(name.slice(-1));
      if (n === 1) q.setFromAxisAngle(Y_AXIS, Math.sin(t * 0.42) * 0.75);
      else if (n === 2) q.setFromAxisAngle(X_AXIS, Math.sin(t * 0.6) * 0.22);
      else if (n === 3) q.setFromAxisAngle(X_AXIS, Math.sin(t * 0.6 + 1.1) * 0.32);
      else q.setFromAxisAngle(Y_AXIS, Math.sin(t * 1.3) * 0.9);
      j.quaternion.copy(base).multiply(q);
    }
  }

  private render(dt = 0) {
    this.renderer.info.reset();
    this.aoCamera.copy(this.camera);
    this.aoCamera.layers.set(0);
    this.composer.render();
    if (this.sim) {
      const tmp = new Vector3();
      for (const [id, a] of this.actors) {
        const st = this.sim.state.agents[id];
        const sub = st.subtaskId ? this.sim.state.subtasks[st.subtaskId] : null;
        this.bubbles.update({
          id, name: st.name, role: st.roleLabel, status: st.status, detail: st.detail,
          task: sub && sub.status !== "completed" ? sub.title : null, progress: sub && sub.status !== "completed" ? sub.progress : null,
        }, a.headPosition(tmp));
      }
    }
    this.bubbles.render(this.camera, dt);
  }

  // ------------------------------------------------------------------ read-outs
  private screenData(): ScreenData {
    const sim = this.sim;
    if (!sim) return { t: 0, phase: "", task: null, agents: [], completed: 0, inProgress: 0, active: 0, helpers: 0, alerts: [], log: [], desks: {}, blocked: false };
    const s = sim.state;
    const task = s.currentTaskId ? s.tasks[s.currentTaskId] : null;
    const subs = task ? task.subtasks.map((id) => s.subtasks[id]) : [];
    const desks: Record<string, string> = {};
    for (const [id, a] of this.actors) {
      const anchorId = a.anchorId;
      if (!anchorId || !a.atGoal()) continue;
      const anchor = this.index.resolve(anchorId);
      if (anchor.desk && a.currentActivity === "typing") desks[`${anchor.desk}_Desk`] = s.agents[id].status;
    }
    return {
      t: s.t, phase: sim.phase(),
      task: task ? {
        title: task.title, status: task.status,
        progress: subs.length ? subs.reduce((a, b) => a + b.progress, 0) / subs.length : 0,
        subtasks: subs.map((st) => ({ title: st.title, agent: s.agents[st.agent]?.name ?? st.agent, progress: st.progress, status: st.status })),
      } : null,
      agents: sim.agentIds.map((id) => ({ name: s.agents[id].name, role: s.agents[id].roleLabel, status: s.agents[id].status, label: STATUS[s.agents[id].status].label, tone: STATUS[s.agents[id].status].tone })),
      completed: s.completedTasks, inProgress: sim.inProgressCount(), active: sim.activeCount(), helpers: sim.agentIds.length,
      alerts: s.alerts.map((a) => a.message), log: s.log.slice(-6).map((l) => (l.agent ? `${s.agents[l.agent]?.name ?? l.agent}: ${l.text}` : l.text)),
      desks, blocked: s.alerts.length > 0,
    };
  }

  snapshot(): OfficeSnapshot | null {
    const sim = this.sim;
    if (!sim) return null;
    const s = sim.state;
    const d = this.screenData();
    return {
      t: s.t, running: this.running, speed: this.speed, phase: d.phase,
      agents: sim.agentIds.map((id) => {
        const st = s.agents[id];
        const a = this.actors.get(id)!;
        const sub = st.subtaskId ? s.subtasks[st.subtaskId] : null;
        const zone = this.index.zoneAt(a.pos[0], a.pos[1]);
        return {
          id, name: st.name, role: st.roleLabel, status: st.status, statusLabel: STATUS[st.status].label, detail: st.detail, tone: STATUS[st.status].tone,
          zone: zone ? this.index.zone(zone).label : "Corridor", task: sub ? sub.title : null, progress: sub ? sub.progress : null,
          recent: [...st.recent].reverse(), walking: a.isWalking, activity: a.currentActivity,
        };
      }),
      task: d.task, completed: d.completed, inProgress: d.inProgress, active: d.active, alerts: d.alerts,
      log: s.log.slice(-14).reverse().map((l) => ({ t: l.t, text: l.text, agent: l.agent })),
      selected: this.selected, selectSeq: this.selectSeq, following: this.rig.following, chat: this.chatView(),
    };
  }

  private chatView(): ChatView | null {
    const sim = this.sim;
    const id = this.selected;
    const actor = id ? this.actors.get(id) : null;
    if (!sim || !id || !actor) return null;
    const st = sim.state.agents[id];
    return {
      agent: id, name: st.name, role: st.roleLabel, status: st.status, statusLabel: STATUS[st.status].label, detail: st.detail, tone: STATUS[st.status].tone,
      messages: [...sim.conversation(id)], tasks: sim.userTasks(id), interaction: actor.interaction, greetingPhase: actor.greetingPhase,
    };
  }

  private emitSnapshot() {
    const s = this.snapshot();
    if (s) this.options.onSnapshot?.(s);
  }

  // ------------------------------------------------------------------ input
  private readonly onPointerDown = (e: PointerEvent) => {
    this.pointerDown.set(e.clientX, e.clientY);
  };

  private readonly onPointerUp = (e: PointerEvent) => {
    if (Math.hypot(e.clientX - this.pointerDown.x, e.clientY - this.pointerDown.y) > 5) return;
    const hit = this.pick(e);
    if (hit) this.select(hit, true);
    else if (this.selected) this.select(null);
  };

  private readonly onPointerMove = (e: PointerEvent) => {
    if (e.buttons) return;
    this.renderer.domElement.style.cursor = this.pick(e) ? "pointer" : "grab";
  };

  private pick(e: PointerEvent): AgentId | null {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hits = this.raycaster.intersectObjects([...this.actors.values()].map((a) => a.proxy), false);
    return (hits[0]?.object.userData.agentId as AgentId | undefined) ?? null;
  }

  private readonly resize = () => {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.composer.setPixelRatio(this.renderer.getPixelRatio());
    this.composer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.rig.resize();
    this.bubbles.setSize(w, h);
    this.needsRender = true;
    if (this.lastView && !this.index.camera(this.lastView)?.zone && !this.rig.following && !this.rig.userMoved) this.view(this.lastView, false);
  };
  private lastView: string | null = "main";

  // ------------------------------------------------------------------ validation helpers
  benchmark(ms = 4000): Promise<{ frames: number; fps: number; avgFrameMs: number; p95FrameMs: number; drawCalls: number; triangles: number }> {
    this.benchmarkFrames = [];
    return new Promise((resolve) => {
      setTimeout(() => {
        const stamps = this.benchmarkFrames ?? [];
        this.benchmarkFrames = null;
        const deltas = stamps.slice(1).map((t, i) => t - stamps[i]).sort((a, b) => a - b);
        const avg = deltas.reduce((a, b) => a + b, 0) / Math.max(1, deltas.length);
        resolve({
          frames: deltas.length, fps: Math.round(1000 / avg), avgFrameMs: +avg.toFixed(2),
          p95FrameMs: +(deltas[Math.floor(deltas.length * 0.95)] ?? 0).toFixed(2),
          drawCalls: this.renderer.info.render.calls, triangles: this.renderer.info.render.triangles,
        });
      }, ms);
    });
  }

  /** GPU resource counts (for the lifecycle check). */
  memory() {
    return { ...this.renderer.info.memory, programs: this.renderer.info.programs?.length ?? 0 };
  }

  dispose() {
    this.disposed = true;
    this.renderer.setAnimationLoop(null);
    this.resizeObserver.disconnect();
    releaseGpuResources(this.scene);
    const canvas = this.renderer.domElement;
    canvas.removeEventListener("pointerdown", this.onPointerDown);
    canvas.removeEventListener("pointerup", this.onPointerUp);
    canvas.removeEventListener("pointermove", this.onPointerMove);
    for (const a of this.actors.values()) a.dispose();
    this.actors.clear();
    this.painter?.dispose();
    this.globe?.dispose();
    this.office?.dispose();
    this.bubbles.dispose();
    this.rig.dispose();
    this.lighting.dispose();
    this.selectionRing.geometry.dispose();
    (this.selectionRing.material as MeshBasicMaterial).dispose();
    this.composer.passes.forEach((p) => p.dispose());
    this.composer.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    canvas.remove();
  }
}

const FX_LAYER = 1;
const X_AXIS = new Vector3(1, 0, 0);
const Y_AXIS = new Vector3(0, 1, 0);

/** Height up to which each obstacle blocks the view. */
function obstacleHeights(): Map<string, number> {
  const out = new Map<string, number>();
  const walls = new Map(OFFICE_LAYOUT.walls.map((w) => [w.id, w]));
  const items = new Map(OFFICE_LAYOUT.items.map((i) => [i.id, i]));
  const base = OFFICE_LAYOUT.architecture.heights.partitionBase ?? 0.42;
  const TYPE_TOP: Record<string, number> = {
    desk_work: 0.62, chair_office: 0.55, chair_lounge: 0.6, sofa: 0.55, table_round: 0.35, stool: 0.3, bookshelf: 1.8, counter: 0.9,
    kiosk: 1.1, screen_stand: 1.7, console_horseshoe: 0.62, display_curved: 2.3, robot_arm: 1.3, test_bench: 0.8, floor_lamp: 1.5,
    equipment_console: 0.55, water_cooler: 1.0, research_robot: 0.75, door_double: 1.55, low_divider: 1.0, glass_rail: 0, glass_enclosure: 0,
  };
  for (const o of OFFICE_LAYOUT.obstacles) {
    const w = walls.get(o.source);
    if (w) {
      out.set(o.id, w.kind === "glass" ? 0 : w.kind === "partition" ? base : w.height);
      continue;
    }
    const it = items.get(o.source);
    const h = Number(it?.params.height ?? NaN);
    out.set(o.id, TYPE_TOP[it?.type ?? ""] ?? (Number.isFinite(h) ? h : 0.8));
  }
  return out;
}

/** Leafy volume of each plant (from the plant builders' reach per kind and variant, as a share of its height). */
function plantCanopies(): { x: number; z: number; r: number; y0: number; y1: number }[] {
  const REACH: Record<string, number[]> = { plant_tall: [0.36, 0.33, 0.75], plant_medium: [0.62, 0.66, 0.2], plant_bush: [0.58, 0.58, 0.58] };
  return OFFICE_LAYOUT.items.filter((i) => REACH[i.type]).map((i) => {
    const h = Number(i.params.height ?? 1);
    const k = REACH[i.type][Number(i.params.variant ?? 0) % 3];
    return { x: i.position[0], z: i.position[2], r: k * h * 0.85, y0: h * 0.3, y1: h };
  });
}
