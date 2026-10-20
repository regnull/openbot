import {
  AnimationClip, AnimationMixer, Group, LoopOnce, LoopRepeat, Object3D, Quaternion, SkinnedMesh,
  type AnimationAction, type Event, type Mesh,
} from "three";
import type { GLTF } from "three/addons/loaders/GLTFLoader.js";
import { CLIPS, clipInfo, crossfadeSeconds, returnClip, type OpenlingClip } from "../../../lib/openlings/animations";
import {
  BLINK_SECONDS, MORPH_TARGETS, blinkAmount, morphWeights, nextBlinkDelay, seededRandom, stepMix,
  type ExpressionMix, type OpenlingExpression,
} from "../../../lib/openlings/expressions";
import {
  PROPS, blendGrip, placeProp, type Loadout, type LoadoutChange, type PlacedMode, type PropAttachment, type PropId,
  type PropPlacement, type SocketName,
} from "../../../lib/openlings/props";
import type { RolePreset } from "../../../lib/openlings/roles";
import { disposeInstance, instantiateOpenling, type OpenlingStats } from "../viewer/loadOpenling";
import type { PropLibrary } from "./PropLibrary";

/** Expression crossfade time constant (s). */
const EXPRESSION_TAU = 0.09;
/** Gesture layer: fade in / out (s) and its peak share of the pose on its bones. */
const GESTURE_IN = 0.35;
const GESTURE_OUT = 0.45;
const GESTURE_PEAK = 0.95;
const SOCKET_NAMES: SocketName[] = [
  "Socket_Glasses", "Socket_Cap", "Socket_BluetoothEarpiece", "Socket_Headphones", "Socket_ResearchGoggles",
  "Socket_Hand_L", "Socket_Hand_R", "Socket_Back", "Socket_Chest", "Socket_DeskInteraction", "Root",
];

export interface CharacterState {
  clip: OpenlingClip | null;
  playing: OpenlingClip | null;
  paused: boolean;
  speed: number;
  expression: OpenlingExpression;
  autoBlink: boolean;
  loadout: Loadout;
  restPose: boolean;
}

/**
 * One animated Openling. Geometry, materials, textures and clips are shared with every
 * other instance; the skeleton, animation mixer, morph weights, blink schedule and prop
 * attachments are its own.
 */
export class OpenlingCharacter {
  /** Position/rotate this group to place the character. */
  readonly root = new Group();
  readonly stats: OpenlingStats;
  private readonly model: Object3D;
  private readonly mixer: AnimationMixer;
  private readonly actions = new Map<OpenlingClip, AnimationAction>();
  private readonly clips = new Map<OpenlingClip, AnimationClip>();
  /** Bone-limited copies of clips (gesture layers), by clip and bones. */
  private readonly masked = new Map<string, AnimationClip>();
  private gestureLayer: { action: AnimationAction; t: number; duration: number } | null = null;
  private readonly faceMeshes: Mesh[] = [];
  private readonly skinned: SkinnedMesh[] = [];
  /** Socket frames: children of the socket bones that equal the character frame in the bind pose. */
  private readonly sockets = new Map<SocketName, Object3D>();
  private readonly propObjects = new Map<PropId, Object3D>();
  /** Held props whose grip depends on the clip (blended every frame). */
  private readonly gripProps = new Map<PropId, PropAttachment>();
  private readonly random: () => number;
  private current: OpenlingClip | null = null;
  private lastLoop: OpenlingClip | null = null;
  private paused = false;
  private speed = 1;
  private rest = false;
  private target: OpenlingExpression = "Neutral";
  private mix: ExpressionMix = { Neutral: 1 };
  private autoBlink = true;
  private blinkTime = -1;
  private blinkIn: number;
  private loadout: Loadout = {};
  private listeners = new Set<() => void>();

  private readonly props: PropLibrary | null;

  constructor(gltf: GLTF, props: PropLibrary | null, options: { seed?: number; maxAnisotropy?: number } = {}) {
    this.props = props;
    const { root, stats } = instantiateOpenling(gltf, options.maxAnisotropy);
    this.model = root;
    this.stats = stats;
    this.root.name = "OpenlingCharacter";
    this.root.add(root);
    this.random = seededRandom(options.seed ?? 1);
    this.blinkIn = 0.6 + this.random() * 2.5;
    root.traverse((o) => {
      if ((o as SkinnedMesh).isSkinnedMesh) this.skinned.push(o as SkinnedMesh);
      const mesh = o as Mesh;
      if (mesh.morphTargetDictionary && "Blink_L" in mesh.morphTargetDictionary) this.faceMeshes.push(mesh);
    });
    if (!this.faceMeshes.length) throw new Error("The Openling asset has no expression morph targets (Openling_Face).");
    this.createSocketFrames();
    this.mixer = new AnimationMixer(root);
    const byName = new Map(gltf.animations.map((c) => [c.name, c] as [string, AnimationClip]));
    for (const info of CLIPS) {
      const clip = byName.get(info.id);
      if (!clip) throw new Error(`The Openling asset has no "${info.id}" animation.`);
      const action = this.mixer.clipAction(clip);
      action.setLoop(info.loop ? LoopRepeat : LoopOnce, info.loop ? Infinity : 1);
      action.clampWhenFinished = !info.loop;
      this.actions.set(info.id, action);
      this.clips.set(info.id, clip);
    }
    this.mixer.addEventListener("finished", this.onFinished);
  }

  /**
   * Socket bones carry the exporter's bone orientation. Each gets a child frame that undoes
   * its bind-pose rotation, so a prop authored in the character frame attaches with the
   * identity (the loaded scene is still in the bind pose here).
   */
  private createSocketFrames() {
    this.model.updateMatrixWorld(true);
    const rootQ = this.model.getWorldQuaternion(new Quaternion()).invert();
    for (const name of SOCKET_NAMES) {
      const bone = this.model.getObjectByName(name);
      if (!bone) throw new Error(`The Openling asset has no "${name}" node.`);
      const frame = new Object3D();
      frame.name = `${name}_Frame`;
      const restQ = rootQ.clone().multiply(bone.getWorldQuaternion(new Quaternion()));
      frame.quaternion.copy(restQ.invert());
      bone.add(frame);
      this.sockets.set(name, frame);
    }
  }

  // ------------------------------------------------------------------ animation
  /**
   * Crossfades to `clip`. Weights are driven here rather than with AnimationAction.fadeOut
   * (which always restarts from weight 1): every fading clip goes from its current weight
   * to 0 on the same curve while the new one rises, so the weights always sum to 1 and the
   * mixer never fills a gap with the wide-A bind pose, even when clips are switched mid-fade.
   */
  play(clip: OpenlingClip, { restart = false }: { restart?: boolean } = {}) {
    const next = this.actions.get(clip)!;
    if (this.rest) {
      this.rest = false;
      this.current = null;
    }
    if (clip === this.current && !restart) return;
    const fade = crossfadeSeconds(this.current, clip);
    const nextWeight = next.isScheduled() ? next.getEffectiveWeight() : 0;
    if (nextWeight === 0 || restart) next.reset();
    next.enabled = true;
    next.play();
    this.fades.clear();
    for (const [, a] of this.actions) {
      if (a === next) continue;
      // isScheduled: playing, or a finished one-shot clamped on its last frame (still weighted)
      const w = a.isScheduled() ? a.getEffectiveWeight() : 0;
      if (w <= 0) { a.stop(); continue; }
      if (fade > 0) this.fades.set(a, { from: w, to: 0 });
      else a.stop();
    }
    if (fade > 0) {
      next.setEffectiveWeight(nextWeight);
      this.fades.set(next, { from: nextWeight, to: 1 });
      this.fadeTime = 0;
      this.fadeLength = fade;
    } else {
      next.setEffectiveWeight(1);
    }
    if (clipInfo(clip).loop) this.lastLoop = clip;
    this.current = clip;
    this.emit();
  }

  private readonly fades = new Map<AnimationAction, { from: number; to: number }>();
  private fadeTime = 0;
  private fadeLength = 0;

  private updateFades(dt: number) {
    if (!this.fades.size) return;
    this.fadeTime += dt;
    const x = Math.min(1, this.fadeTime / this.fadeLength);
    const s = x * x * (3 - 2 * x);
    for (const [a, f] of this.fades) a.setEffectiveWeight(f.from + (f.to - f.from) * s);
    if (x >= 1) {
      for (const [a, f] of this.fades) if (f.to === 0) a.stop();
      this.fades.clear();
    }
  }

  /** Sum of the clip weights the mixer is blending (1 outside the bind pose). */
  totalWeight(): number {
    let w = 0;
    for (const a of this.actions.values()) if (a.isScheduled()) w += a.getEffectiveWeight();
    return w;
  }

  private readonly onFinished = (e: Event & { action?: AnimationAction }) => {
    const finished = [...this.actions].find(([, a]) => a === e.action)?.[0];
    if (!finished || finished !== this.current || clipInfo(finished).loop) return;
    this.play(returnClip(finished, this.lastLoop));
  };

  /**
   * Plays a one-shot clip as a layer over the current one, limited to the rotations of some bones:
   * the rest of the body keeps its pose (a seated Openling waves with its arm without standing up).
   * The layer's weight rises and falls on a smooth curve, so neither end snaps. Returns its length (s).
   */
  gesture(clip: OpenlingClip, bones: readonly string[]): number {
    const src = this.clips.get(clip)!;
    const key = `${clip}|${bones.join(",")}`;
    let masked = this.masked.get(key);
    if (!masked) {
      const tracks = src.tracks.filter((t) => t.name.endsWith(".quaternion") && bones.includes(t.name.slice(0, t.name.lastIndexOf("."))));
      masked = new AnimationClip(`${clip}_layer`, src.duration, tracks);
      this.masked.set(key, masked);
    }
    const action = this.mixer.clipAction(masked);
    if (this.gestureLayer && this.gestureLayer.action !== action) this.gestureLayer.action.stop();
    action.setLoop(LoopOnce, 1);
    action.clampWhenFinished = true;
    action.reset();
    action.setEffectiveWeight(0);
    action.play();
    this.gestureLayer = { action, t: 0, duration: src.duration };
    return src.duration;
  }

  /** A gesture layer is playing. */
  get gesturing(): boolean {
    return !!this.gestureLayer;
  }

  private updateGesture(dt: number) {
    const g = this.gestureLayer;
    if (!g) return;
    g.t += dt;
    if (g.t >= g.duration) {
      g.action.stop();
      this.gestureLayer = null;
      return;
    }
    const x = Math.max(0, Math.min(1, g.t / GESTURE_IN, (g.duration - g.t) / GESTURE_OUT));
    // the mixer averages the layer with the base clip by weight: w / (1 + w) is the layer's share
    const share = GESTURE_PEAK * x * x * (3 - 2 * x);
    g.action.setEffectiveWeight(share / (1 - share));
  }

  /** Bind pose (wide-A), as in the reference renders: for golden-master comparisons. */
  restPose() {
    this.gestureLayer = null;
    this.fades.clear();
    this.mixer.stopAllAction();
    for (const m of this.skinned) m.skeleton.pose();
    this.rest = true;
    this.current = null;
    this.emit();
  }

  setPaused(paused: boolean) {
    this.paused = paused;
    this.emit();
  }

  setSpeed(speed: number) {
    this.speed = speed;
    this.emit();
  }

  /** Advances one clip to a time, paused (for deterministic captures). */
  seek(seconds: number) {
    if (!this.current) return;
    const a = this.actions.get(this.current)!;
    this.fades.clear();
    for (const other of this.actions.values()) if (other !== a) other.stop();
    a.reset();
    a.setEffectiveWeight(1);
    a.play();
    a.time = seconds;
    this.mixer.update(0);
    this.updateGrips();
  }

  // ------------------------------------------------------------------ face
  setExpression(expression: OpenlingExpression, { instant = false }: { instant?: boolean } = {}) {
    this.target = expression;
    if (instant) this.mix = { [expression]: 1 };
    this.emit();
  }

  setAutoBlink(on: boolean) {
    this.autoBlink = on;
    if (!on) this.blinkTime = -1;
    this.emit();
  }

  blink() {
    this.blinkTime = 0;
  }

  /** Holds the eyes at a fixed blink amount (null = back to normal); for captures. */
  private heldBlink: number | null = null;
  holdBlink(amount: number | null) {
    this.heldBlink = amount;
    this.applyFace();
  }

  private applyFace() {
    const blink = this.heldBlink ?? (this.blinkTime >= 0 ? blinkAmount(this.blinkTime) : 0);
    const w = morphWeights(this.mix, blink);
    for (const mesh of this.faceMeshes) {
      const dict = mesh.morphTargetDictionary!;
      const infl = mesh.morphTargetInfluences!;
      for (const name of MORPH_TARGETS) {
        const i = dict[name];
        if (i !== undefined) infl[i] = w[name];
      }
    }
  }

  // ------------------------------------------------------------------ props
  /** Places, moves or removes a prop; conflicting props come off. */
  place(id: PropId, placement: PropPlacement): LoadoutChange {
    const change = placeProp(this.loadout, id, placement);
    this.setLoadout(change.loadout);
    return change;
  }

  /** Makes the attached props match `loadout` exactly (re-parents props that moved). */
  setLoadout(loadout: Loadout) {
    for (const [id, obj] of [...this.propObjects]) {
      if (loadout[id] !== this.loadout[id]) {
        obj.removeFromParent();
        this.propObjects.delete(id);
        this.gripProps.delete(id);
      }
    }
    if (this.props) {
      for (const [id, placement] of Object.entries(loadout) as [PropId, PlacedMode][]) {
        if (this.propObjects.has(id)) continue;
        const spec = PROPS[id].placements[placement];
        if (!spec) continue;
        const obj = this.props.instantiate(id);
        const o = spec.offset;
        if (o?.position) obj.position.set(...o.position);
        if (o?.quaternion) obj.quaternion.set(...o.quaternion);
        this.sockets.get(spec.socket)!.add(obj);
        this.propObjects.set(id, obj);
        if (spec.clipOffsets) this.gripProps.set(id, spec);
      }
    }
    this.loadout = { ...loadout };
    this.emit();
  }

  clearProps() {
    this.setLoadout({});
  }

  applyRole(role: RolePreset) {
    let loadout: Loadout = {};
    for (const p of role.props) loadout = placeProp(loadout, p.id, p.placement).loadout;
    this.setLoadout(loadout);
    this.setExpression(role.expression);
    this.play(role.clip);
  }

  /** The prop object for a placed prop (for tests and inspection). */
  propObject(id: PropId): Object3D | undefined {
    return this.propObjects.get(id);
  }

  socketFrame(name: SocketName): Object3D | undefined {
    return this.sockets.get(name);
  }

  /** Weight of every clip in the current blend (sums to 1 outside the bind pose). */
  clipWeights(): Partial<Record<OpenlingClip, number>> {
    const w: Partial<Record<OpenlingClip, number>> = {};
    for (const [id, a] of this.actions) if (a.isScheduled() && a.getEffectiveWeight() > 0) w[id] = a.getEffectiveWeight();
    return w;
  }

  private updateGrips() {
    if (!this.gripProps.size) return;
    const weights = this.rest ? {} : this.clipWeights();
    for (const [id, spec] of this.gripProps) {
      const g = blendGrip(spec, weights);
      const obj = this.propObjects.get(id)!;
      obj.position.set(...g.position);
      obj.quaternion.set(...g.quaternion);
    }
  }

  // ------------------------------------------------------------------ frame
  update(dt: number) {
    if (!this.rest) {
      this.updateFades(dt);
      this.updateGesture(this.paused ? 0 : dt * this.speed);
      this.mixer.update(this.paused ? 0 : dt * this.speed);
    }
    this.updateGrips();
    const k = 1 - Math.exp(-dt / EXPRESSION_TAU);
    this.mix = stepMix(this.mix, this.target, k);
    if (this.autoBlink && this.blinkTime < 0) {
      this.blinkIn -= dt;
      if (this.blinkIn <= 0) {
        this.blinkTime = 0;
        this.blinkIn = nextBlinkDelay(this.random);
      }
    }
    if (this.blinkTime >= 0) {
      this.blinkTime += dt;
      if (this.blinkTime > BLINK_SECONDS) this.blinkTime = -1;
    }
    this.applyFace();
  }

  get state(): CharacterState {
    return {
      clip: this.current,
      playing: this.current,
      paused: this.paused,
      speed: this.speed,
      expression: this.target,
      autoBlink: this.autoBlink,
      loadout: { ...this.loadout },
      restPose: this.rest,
    };
  }

  /** Current morph influences on the face, by target name (for validation). */
  morphInfluences(): Record<string, number> {
    const mesh = this.faceMeshes[0];
    const out: Record<string, number> = {};
    for (const [name, i] of Object.entries(mesh.morphTargetDictionary!)) out[name] = +mesh.morphTargetInfluences![i].toFixed(4);
    return out;
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit() {
    for (const fn of this.listeners) fn();
  }

  dispose() {
    this.mixer.removeEventListener("finished", this.onFinished);
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.model);
    for (const obj of this.propObjects.values()) obj.removeFromParent();
    this.propObjects.clear();
    this.gripProps.clear();
    this.listeners.clear();
    this.root.removeFromParent();
    // The instance's own GPU data is its skeleton's bone texture; geometry, materials,
    // textures and clips belong to the shared GLB caches.
    disposeInstance(this.model);
  }
}
