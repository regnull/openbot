import { CylinderGeometry, Mesh, MeshBasicMaterial, Vector3, type Object3D } from "three";
import { WALK_ROOT_SPEED, clipInfo, type OpenlingClip } from "../../../lib/openlings/animations";
import { PROPS, buildLoadout, type Loadout } from "../../../lib/openlings/props";
import { rolePreset } from "../../../lib/openlings/roles";
import { agentProfile, isSeatedActivity, type Activity, type AgentGoal, type AgentId } from "../../../lib/office/agents";
import { angleDelta, yawDir, yawTo, type LayoutIndex, type OfficeAnchor, type Vec2 } from "../../../lib/office/layout";
import type { NavGraph } from "../../../lib/office/nav";
import { STATUS, type AgentStatus } from "../../../lib/office/status";
import type { OpenlingCharacter } from "../../openlings/runtime/OpenlingCharacter";

/** Demo walk: the Walk clip plays this much faster than authored, and the root moves to match. */
export const WALK_RATE = 1.75;
const TURN_RATE = 3.4; // rad/s
const SEAT_SECONDS = 0.75;
const AVOID_RADIUS = 0.66;
/** Bones a seated Openling waves with (the Wave clip's arm and head, over its seated pose). */
const SEATED_WAVE_BONES = ["UpperArm_R", "Hand_R", "Head", "Sprout"] as const;
/** The full Wave hands back to the loop before its last frames: the greeting ends as that blend settles. */
const WAVE_TAIL = 0.2;

/**
 * Greeting overlay (Phase 1.1): a short interaction on top of the agent's real task, never a
 * replacement for it. "wait": finishing a sit / stand / final approach first; "turn": facing the
 * viewer; "wave"; "back": turning back to where it was facing. Goals that arrive meanwhile wait.
 */
export type GreetingPhase = "wait" | "turn" | "wave" | "back";
export type AgentInteraction = "normal" | "greeting" | "resuming";

type Action =
  | { kind: "walk"; points: Vec2[]; i: number; backward: boolean; held: number; route?: boolean }
  | { kind: "turn"; yaw: number }
  | { kind: "sit"; anchor: OfficeAnchor; t: number }
  | { kind: "stand"; anchor: OfficeAnchor; t: number }
  | { kind: "perform" };

const ACTIVITY_CLIP: Record<Activity, OpenlingClip> = {
  idle: "Idle", waiting: "Idle", coffee: "Idle", testing: "Idle", inspecting: "Idle",
  commanding: "Reporting", reading: "Reporting", presenting: "Reporting", reporting: "Reporting",
  typing: "Typing", seated: "SitIdle", resting: "SitIdle", sleeping: "SitIdle",
};

export interface ActorWorld {
  index: LayoutIndex;
  nav: NavGraph;
  /** Dynamic office objects by item id (sliding chairs and stools). */
  dynamic: Map<string, Object3D>;
  actors: () => readonly AgentActor[];
}

/**
 * One Openling in the office: walks real routes between anchors, turns, sits (its chair rolls
 * under it), stands, and performs its activity with the matching clip, face and props.
 * Logic runs in fixed steps (`step`); animation advances per frame (`frame`).
 */
export class AgentActor {
  readonly id: AgentId;
  readonly character: OpenlingCharacter;
  /** Invisible picking volume (raycast target for selection). */
  readonly proxy: Mesh;
  pos: Vec2;
  yaw: number;
  status: AgentStatus = "idle";
  goal: AgentGoal;
  private goalKey = "";
  private reached = false;
  private pending: AgentGoal | null = null;
  private queue: Action[] = [];
  private at: { anchor: OfficeAnchor; seated: boolean } | null = null;
  private activity: Activity = "idle";
  private readonly world: ActorWorld;
  private readonly baseLoadout: Loadout;
  private walking = false;
  private clip: OpenlingClip | null = null;
  private readonly head = new Vector3();
  /** Distance walked (for the performance/validation report). */
  odometer = 0;
  private greeting: { phase: GreetingPhase; face: number | null; back: number | null; t: number; length: number; seated: boolean } | null = null;
  /** Greetings played (for validation: one per new selection). */
  greetings = 0;

  constructor(id: AgentId, character: OpenlingCharacter, world: ActorWorld) {
    this.id = id;
    this.character = character;
    this.world = world;
    const profile = agentProfile(id);
    const role = rolePreset(profile.preset);
    this.baseLoadout = buildLoadout(profile.props ?? role.props);
    this.goal = { ...profile.start };
    this.proxy = new Mesh(new CylinderGeometry(0.34, 0.34, 1.0, 12), new MeshBasicMaterial({ visible: false }));
    this.proxy.position.y = 0.5;
    this.proxy.userData.agentId = id;
    character.root.add(this.proxy);
    // start in place, already performing
    const a = world.index.resolve(profile.start.anchor);
    this.pos = [a.position[0], a.position[2]];
    this.yaw = a.yaw;
    this.at = { anchor: a, seated: isSeatedActivity(profile.start.activity) && a.kind === "sit" };
    if (this.at.seated && a.chair) this.placeChair(a, 1);
    this.goalKey = key(profile.start);
    this.applyActivity(profile.start.activity, true);
    this.reached = true;
    this.sync();
  }

  /** At its goal anchor and performing the goal activity. */
  atGoal(): boolean {
    return this.reached && !this.pending && this.goalKey === key(this.goal);
  }

  /** At exactly this goal (the simulation asks about the goal it set, not the actor's last one). */
  atGoalFor(goal: AgentGoal): boolean {
    return this.atGoal() && this.goalKey === key(goal);
  }

  get isWalking(): boolean {
    return this.walking;
  }

  get anchorId(): string | null {
    return this.at?.anchor.id ?? null;
  }

  get currentActivity(): Activity {
    return this.activity;
  }

  setGoal(goal: AgentGoal) {
    if (key(goal) === key(this.goal) && !this.pending) return;
    this.goal = { ...goal };
    this.pending = { ...goal };
    this.reached = false;
  }

  setStatus(status: AgentStatus) {
    this.status = status;
    // a greeting keeps its happy face; the status's face comes back when it ends
    if (this.activity !== "sleeping" && !this.greeting) this.character.setExpression(STATUS[status].expression);
  }

  wave() {
    if (this.at?.seated || this.walking || this.greeting) return;
    this.character.play("Wave", { restart: true });
  }

  /**
   * Notices the viewer: once it is safe (not mid sit, stand or final approach; a walk pauses on its
   * route), it turns toward `faceYaw` when given (only where there is room), waves once with a happy
   * face, turns back and carries on. Seated Openlings wave with the arm only and stay seated.
   * Returns false while a greeting is already running (no repeated waves).
   */
  greet(faceYaw: number | null): boolean {
    if (this.greeting) return false;
    this.greeting = { phase: "wait", face: faceYaw, back: null, t: 0, length: 0, seated: false };
    this.greetings++;
    return true;
  }

  get interaction(): AgentInteraction {
    if (!this.greeting) return "normal";
    return this.greeting.phase === "back" ? "resuming" : "greeting";
  }

  get greetingPhase(): GreetingPhase | null {
    return this.greeting?.phase ?? null;
  }

  /** Seated at its anchor (in the seat, not getting up or sitting down). */
  get seated(): boolean {
    return !!this.at?.seated && !this.queue.some((a) => a.kind === "sit" || a.kind === "stand");
  }

  /** Carries something in a hand (it sweeps further out than the body when the Openling turns). */
  get holdsProps(): boolean {
    return Object.values(this.baseLoadout).some((w) => w === "heldLeft" || w === "heldRight");
  }

  /** On a free stretch of a route (where pausing to greet blocks no seat, desk or doorway approach). */
  get onRoute(): boolean {
    const a = this.queue[0];
    return a?.kind === "walk" && !!a.route;
  }

  /** Runs the greeting; true while it holds the actor (its queue and any new goal wait). */
  private stepGreeting(dt: number): boolean {
    const g = this.greeting!;
    if (g.phase === "wait") {
      const cur = this.queue[0];
      const settled = !cur || (cur.kind === "walk" && cur.route);
      if (!settled) return false; // finish the sit, stand, turn or approach first
      if (cur) {
        this.setWalk(false);
        this.play("Idle");
      }
      g.seated = !!this.at?.seated && !cur;
      if (!g.seated && g.face !== null && Math.abs(angleDelta(this.yaw, g.face)) > 0.05) {
        g.back = cur ? null : this.yaw; // a paused walk turns back by itself when it resumes
        g.phase = "turn";
      } else {
        this.startWave();
      }
      return true;
    }
    if (g.phase === "turn" || g.phase === "back") {
      const target = g.phase === "turn" ? g.face! : g.back!;
      const d = angleDelta(this.yaw, target);
      if (Math.abs(d) < 0.04) {
        this.yaw = target;
        this.setWalk(false);
        this.play("Idle");
        if (g.phase === "turn") this.startWave();
        else this.endGreeting();
        return true;
      }
      this.setWalk(true, 0.7, false);
      this.yaw += Math.sign(d) * Math.min(Math.abs(d), TURN_RATE * dt);
      return true;
    }
    // wave
    g.t += dt;
    if (g.t >= g.length) {
      // turn back to where it was facing, unless a new goal already waits (it turns toward that instead)
      if (g.back !== null && !this.pending) g.phase = "back";
      else this.endGreeting();
    }
    return true;
  }

  private startWave() {
    const g = this.greeting!;
    g.phase = "wave";
    g.t = 0;
    if (this.activity === "sleeping" && g.seated) this.character.holdBlink(null); // it wakes up to say hi
    this.character.setExpression("Happy");
    if (g.seated) {
      g.length = this.character.gesture("Wave", SEATED_WAVE_BONES);
    } else {
      // the one-shot hands back to the loop that was playing (Idle, Reporting) by itself when it ends
      this.character.play("Wave", { restart: true });
      g.length = clipInfo("Wave").duration - WAVE_TAIL;
    }
  }

  private endGreeting() {
    this.greeting = null;
    // performing at its anchor: back to the activity's own loop (a turn in place played Walk / Idle)
    if (!this.queue.length && !this.walking) this.play(ACTIVITY_CLIP[this.activity]);
    if (this.activity === "sleeping" && this.at?.seated) {
      this.character.setExpression("Neutral");
      this.character.holdBlink(1);
    } else {
      this.character.setExpression(STATUS[this.status].expression);
    }
  }

  headPosition(out = this.head): Vector3 {
    const s = this.character.socketFrame("Socket_Cap");
    if (s) s.getWorldPosition(out);
    else out.set(this.pos[0], 0.9, this.pos[1]);
    return out;
  }

  // ------------------------------------------------------------------ planning
  private plan(goal: AgentGoal) {
    const { index, nav } = this.world;
    const target = index.resolve(goal.anchor);
    const actions: Action[] = [];
    this.goalKey = key(goal);
    // already there: change what we do, in place
    if (this.at && this.at.anchor.id === target.id) {
      const wantSeat = isSeatedActivity(goal.activity) && target.kind === "sit";
      if (wantSeat && !this.at.seated) actions.push({ kind: "sit", anchor: target, t: 0 });
      if (!wantSeat && this.at.seated) actions.push({ kind: "stand", anchor: target, t: 0 });
      actions.push({ kind: "perform" });
      this.queue = actions;
      this.activity = goal.activity;
      return;
    }
    let from: Vec2 = [...this.pos];
    // leave the current spot
    if (this.at) {
      const here = this.at.anchor;
      if (this.at.seated) actions.push({ kind: "stand", anchor: here, t: 0 });
      if (here.approach) {
        const ap: Vec2 = [here.approach[0], here.approach[2]];
        actions.push({ kind: "turn", yaw: yawTo(this.pos[0], this.pos[1], ap[0], ap[1]) });
        actions.push({ kind: "walk", points: [from, ap], i: 1, backward: false, held: 0 });
        from = ap;
      }
    }
    const route = nav.routeToNode(from, nav.goalNode(target));
    if (route && route.points.length > 1) actions.push({ kind: "walk", points: route.points, i: 1, backward: false, held: 0, route: true });
    const last: Vec2 = route ? route.points[route.points.length - 1] : from;
    const tp: Vec2 = [target.position[0], target.position[2]];
    if (target.approach) {
      const seat = target.kind === "sit";
      const f = yawDir(target.yaw);
      const backIn = seat && (target.approach[0] - tp[0]) * f[0] + (target.approach[2] - tp[1]) * f[1] > 0;
      if (backIn) {
        actions.push({ kind: "turn", yaw: target.yaw });
        actions.push({ kind: "walk", points: [last, tp], i: 1, backward: true, held: 0 });
      } else {
        actions.push({ kind: "walk", points: [last, tp], i: 1, backward: false, held: 0 });
      }
      actions.push({ kind: "turn", yaw: target.yaw });
      if (seat && isSeatedActivity(goal.activity)) actions.push({ kind: "sit", anchor: target, t: 0 });
    } else {
      actions.push({ kind: "turn", yaw: target.yaw });
    }
    actions.push({ kind: "perform" });
    this.queue = actions;
    this.at = null;
    this.activity = goal.activity;
    this.nextAnchor = target;
  }
  private nextAnchor: OfficeAnchor | null = null;

  // ------------------------------------------------------------------ fixed step
  step(dt: number) {
    if (this.greeting && this.stepGreeting(dt)) {
      this.sync();
      return;
    }
    if (this.pending) {
      const cur = this.queue[0];
      const busy = cur && (cur.kind === "sit" || cur.kind === "stand");
      if (!busy) {
        const g = this.pending;
        this.pending = null;
        this.queue = [];
        this.reached = false;
        this.plan(g);
      }
    }
    const a = this.queue[0];
    if (!a) return;
    switch (a.kind) {
      case "turn": {
        const d = angleDelta(this.yaw, a.yaw);
        if (Math.abs(d) < 0.04) {
          this.yaw = a.yaw;
          this.queue.shift();
          break;
        }
        this.setWalk(true, 0.7, false);
        this.yaw += Math.sign(d) * Math.min(Math.abs(d), TURN_RATE * dt);
        break;
      }
      case "walk":
        this.stepWalk(a, dt);
        break;
      case "sit": {
        if (a.t === 0) {
          this.setWalk(false);
          this.at = { anchor: a.anchor, seated: true };
          this.pos = [a.anchor.position[0], a.anchor.position[2]];
          this.yaw = a.anchor.yaw;
          this.play(this.activity === "typing" ? "Typing" : "SitIdle");
          this.updateDeskProps(this.activity === "typing");
        }
        a.t += dt;
        if (a.anchor.chair) this.placeChair(a.anchor, smooth(a.t / SEAT_SECONDS));
        if (a.t >= SEAT_SECONDS) this.queue.shift();
        break;
      }
      case "stand": {
        if (a.t === 0) {
          this.updateDeskProps(false);
          this.play("Idle");
        }
        a.t += dt;
        if (a.anchor.chair) this.placeChair(a.anchor, 1 - smooth(a.t / SEAT_SECONDS));
        if (a.t >= SEAT_SECONDS) {
          if (this.at) this.at.seated = false;
          this.queue.shift();
        }
        break;
      }
      case "perform": {
        this.setWalk(false);
        const target = this.nextAnchor ?? this.at?.anchor;
        if (target && !this.at) this.at = { anchor: target, seated: false };
        if (this.at && this.at.anchor.kind === "sit" && isSeatedActivity(this.activity) && !this.at.seated) this.at.seated = true;
        this.nextAnchor = null;
        this.applyActivity(this.activity, false);
        this.queue.shift();
        this.reached = true;
        break;
      }
    }
    this.sync();
  }

  private stepWalk(a: Extract<Action, { kind: "walk" }>, dt: number) {
    const target = a.points[a.i];
    const dx = target[0] - this.pos[0], dz = target[1] - this.pos[1];
    const dist = Math.hypot(dx, dz);
    const heading = Math.atan2(dx, dz);
    const faceYaw = a.backward ? heading + Math.PI : heading;
    const turn = angleDelta(this.yaw, faceYaw);
    if (dist < 1e-4) {
      a.i++;
      if (a.i >= a.points.length) this.queue.shift();
      return;
    }
    // big heading change: turn in place first (feet keep stepping)
    if (Math.abs(turn) > 0.9) {
      this.setWalk(true, 0.7, false);
      this.yaw += Math.sign(turn) * Math.min(Math.abs(turn), TURN_RATE * dt);
      return;
    }
    // simple courtesy: hold while another Openling stands right ahead
    if (this.blockedAhead(heading) && a.held < 2.5) {
      a.held += dt;
      this.setWalk(false);
      this.play("Idle");
      return;
    }
    this.setWalk(true, WALK_RATE, a.backward);
    const v = WALK_ROOT_SPEED * WALK_RATE;
    const stepLen = Math.min(dist, v * dt);
    // keep right when another walker comes the other way (only where there is room)
    let mx = dx / dist, mz = dz / dist;
    if (!a.backward && dist > 0.5 && this.oncoming(heading)) {
      const k = 0.42; // ~24 degrees to the right
      const rx = mx * Math.cos(k) + mz * Math.sin(k), rz = -mx * Math.sin(k) + mz * Math.cos(k);
      const probe: Vec2 = [this.pos[0] + rx * 0.45, this.pos[1] + rz * 0.45];
      if (this.world.nav.clear(this.pos, probe, 0.2)) { mx = rx; mz = rz; }
    }
    this.yaw += Math.sign(turn) * Math.min(Math.abs(turn), TURN_RATE * dt);
    this.pos = [this.pos[0] + mx * stepLen, this.pos[1] + mz * stepLen];
    this.odometer += stepLen;
    if (stepLen >= dist - 1e-6) {
      this.pos = [target[0], target[1]];
      a.i++;
      if (a.i >= a.points.length) this.queue.shift();
    }
  }

  private oncoming(heading: number): boolean {
    const f = yawDir(heading);
    for (const o of this.world.actors()) {
      if (o === this || !o.isWalking) continue;
      const dx = o.pos[0] - this.pos[0], dz = o.pos[1] - this.pos[1];
      const d = Math.hypot(dx, dz);
      if (d > 1.6 || d < 1e-3 || (dx * f[0] + dz * f[1]) / d < 0.7) continue;
      const of = yawDir(o.yaw);
      if (of[0] * f[0] + of[1] * f[1] < -0.5) return true;
    }
    return false;
  }

  private blockedAhead(heading: number): boolean {
    const f = yawDir(heading);
    for (const o of this.world.actors()) {
      if (o === this || !o.isWalking) continue;
      const dx = o.pos[0] - this.pos[0], dz = o.pos[1] - this.pos[1];
      const d = Math.hypot(dx, dz);
      if (d > AVOID_RADIUS || d < 1e-3) continue;
      if ((dx * f[0] + dz * f[1]) / d < 0.45) continue;
      // head-on walkers steer around each other instead of waiting
      const of = yawDir(o.yaw);
      if (of[0] * f[0] + of[1] * f[1] < -0.5) continue;
      // same direction: the follower waits for the one ahead
      return true;
    }
    return false;
  }

  // ------------------------------------------------------------------ visuals
  private setWalk(on: boolean, rate = WALK_RATE, backward = false) {
    if (on) {
      this.walking = true;
      this.updateDeskProps(false);
      this.play("Walk");
      this.character.setSpeed(backward ? -rate : rate);
    } else if (this.walking) {
      this.walking = false;
      this.character.setSpeed(1);
    }
  }

  private play(clip: OpenlingClip) {
    if (this.clip === clip && this.character.state.clip === clip) return;
    this.clip = clip;
    this.character.play(clip);
  }

  private applyActivity(activity: Activity, instant: boolean) {
    this.activity = activity;
    this.character.setSpeed(1);
    const clip = ACTIVITY_CLIP[activity];
    this.play(clip);
    if (instant) this.character.update(0.37 * (agentRank(this.id) + 1));
    this.updateDeskProps(activity === "typing");
    if (activity === "sleeping") {
      this.character.setExpression("Neutral");
      this.character.holdBlink(1);
    } else {
      this.character.holdBlink(null);
      this.character.setExpression(STATUS[this.status].expression);
    }
  }

  /** The laptop sits on the desk only while the Openling types there. */
  private updateDeskProps(onDesk: boolean) {
    const want: Loadout = {};
    for (const [id, where] of Object.entries(this.baseLoadout) as [keyof typeof PROPS, Loadout[keyof typeof PROPS]][]) {
      if (where === "desk" && !onDesk) continue;
      want[id] = where;
    }
    if (onDesk && !want.laptop) want.laptop = "desk";
    const cur = this.character.state.loadout;
    const same = Object.keys(want).length === Object.keys(cur).length && Object.entries(want).every(([k, v]) => cur[k as keyof Loadout] === v);
    if (!same) this.character.setLoadout(want);
  }

  private placeChair(anchor: OfficeAnchor, k: number) {
    const chair = anchor.chair ? this.world.dynamic.get(anchor.chair) : undefined;
    if (!chair) return;
    const p = this.world.index.item(anchor.chair!).params;
    const r = p.restPose!, s = p.seatPose!;
    const ry = p.restYaw!, sy = p.seatYaw!;
    chair.position.set(r[0] + (s[0] - r[0]) * k, 0, r[2] + (s[2] - r[2]) * k);
    chair.rotation.set(0, ry + angleDelta(ry, sy) * k, 0);
  }

  /** Copies the logical position to the character root. */
  private sync() {
    this.character.root.position.set(this.pos[0], 0, this.pos[1]);
    this.character.root.rotation.set(0, this.yaw, 0);
  }

  /** Per rendered frame: animation, face and props (dt already scaled by the simulation speed). */
  frame(dt: number) {
    this.character.update(dt);
  }

  dispose() {
    this.proxy.geometry.dispose();
    (this.proxy.material as MeshBasicMaterial).dispose();
    this.character.dispose();
  }
}

function key(g: AgentGoal) {
  return `${g.anchor}/${g.activity}`;
}

function smooth(x: number) {
  const t = Math.min(1, Math.max(0, x));
  return t * t * (3 - 2 * t);
}

const RANK: AgentId[] = ["commander", "reporter", "ops", "tester", "researcher", "coder", "worker1", "worker2"];
function agentRank(id: AgentId) {
  return RANK.indexOf(id);
}
