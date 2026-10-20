import { describe, expect, it } from "vitest";
import { AGENTS, type AgentId } from "./agents";
import { LayoutIndex, OFFICE_LAYOUT, angleDelta, pointInPolygon, type Vec2 } from "./layout";
import { APPROACH_SUFFIX, NavGraph, obstacleDist } from "./nav";
import { OfficeSimulation, STEP, type TimedEvent, type WorldProbe } from "./simulation";
import { STATUS, bubbleFor, primaryStatus } from "./status";

const index = new LayoutIndex();
const nav = new NavGraph(index);
const L = OFFICE_LAYOUT;

const REQUIRED_ANCHORS = [
  "Lobby_Entry", "Lobby_Wait", "Lobby_Exit", "Lobby_CheckIn", "Lobby_CameraFocus",
  "Command_Work", "Command_ReceiveReport", "Command_Approach", "Command_VisitorWait", "Command_CameraFocus",
  "Research_Work", "Research_Reading", "Research_Discuss", "Research_Exit", "Research_CameraFocus",
  "Dev_Exit", "Test_Work", "Test_Inspect", "Test_Exit", "DevTest_CameraFocus",
  "Reporting_Presenter", "Reporting_Approach", "Reporting_Seat_01", "Reporting_Seat_02", "Reporting_Exit", "Reporting_CameraFocus",
  "Ops_Inspect", "Ops_Desk", "Ops_AlertReview", "Ops_Exit", "Ops_CameraFocus",
  "Break_Approach", "Break_Sofa_Seat", "Break_Chair_Seat", "Break_Coffee", "Break_Exit", "Break_CameraFocus",
  ...[1, 2, 3, 4, 5, 6].flatMap((n) => ["Arrive", "Seat", "Work", "Exit"].map((k) => `Desk_0${n}_${k}`)),
];

describe("office layout contract", () => {
  it("has the eight zones in the approved arrangement", () => {
    const c = (id: string) => L.zones.find((z) => z.id === id)!.center;
    expect(L.zones.map((z) => z.number).sort()).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    // entrance front-centre, Command Hub rear-centre, Research rear-left, Dev/Test rear-right
    expect(c("lobby")[1]).toBeGreaterThan(3);
    expect(Math.abs(c("lobby")[0])).toBeLessThan(0.5);
    expect(c("command")[1]).toBeLessThan(-3);
    expect(Math.abs(c("command")[0])).toBeLessThan(0.5);
    expect(c("research")[0]).toBeLessThan(-3);
    expect(c("research")[1]).toBeLessThan(-3);
    expect(c("devtest")[0]).toBeGreaterThan(3);
    expect(c("devtest")[1]).toBeLessThan(-3);
    // Break front-left, Ops right, Workers left-centre, Reporting right-centre
    expect(c("break")[0]).toBeLessThan(-5);
    expect(c("ops")[0]).toBeGreaterThan(5);
    expect(c("workers")[0]).toBeLessThan(-1);
    expect(c("workers")[0]).toBeGreaterThan(c("break")[0]);
    expect(c("reporting")[0]).toBeGreaterThan(1);
    expect(c("reporting")[0]).toBeLessThan(c("ops")[0]);
  });

  it("defines every required interaction anchor, inside its own zone", () => {
    for (const id of REQUIRED_ANCHORS) expect(index.hasAnchor(id), id).toBe(true);
    for (const a of L.anchors) {
      if (a.kind === "camera") continue;
      const zone = L.zones.find((z) => z.id === a.zone)!;
      const [x, , z] = a.position;
      // lobby anchors may stand on the porch; the zone polygon includes it
      expect(pointInPolygon(x, z, zone.polygon), `${a.id} in ${a.zone}`).toBe(true);
    }
  });

  it("uses unique ids across walls, items and anchors", () => {
    const ids = [...L.walls.map((w) => w.id), ...L.items.map((i) => i.id), ...L.anchors.map((a) => a.id)];
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("sizes seats and desks to the Openling rig", () => {
    expect(L.character.seatHeight).toBeCloseTo(0.132, 3);
    expect(L.character.deskHeight).toBeCloseTo(0.15, 3);
    expect(L.character.walkSpeed).toBeCloseTo(0.142, 3);
    for (const it of L.items.filter((i) => i.type === "desk_work")) expect(it.params.height).toBeCloseTo(0.15, 3);
    // every desk work spot is exactly the laptop reach in front of its seat
    for (const a of L.anchors.filter((x) => x.kind === "work" && x.seat)) {
      const seat = index.anchor(a.seat!);
      const d = Math.hypot(a.position[0] - seat.position[0], a.position[2] - seat.position[2]);
      expect(d).toBeCloseTo(L.character.deskReach, 3);
      expect(a.position[1]).toBeCloseTo(0.15, 3);
    }
  });

  it("keeps standing anchors and approach points clear of furniture and walls", () => {
    const pts: [string, Vec2, Set<string>][] = [];
    for (const a of L.anchors) {
      if (a.alias) continue;
      if (a.approach) pts.push([a.id + APPROACH_SUFFIX, [a.approach[0], a.approach[2]], new Set(a.ignore ?? [])]);
      else if (a.kind === "stand" || a.kind === "approach") pts.push([a.id, [a.position[0], a.position[2]], new Set()]);
    }
    for (const [id, p, ignore] of pts) {
      for (const o of L.obstacles) {
        if (ignore.has(o.source)) continue;
        expect(obstacleDist(o, p, p), `${id} vs ${o.id}`).toBeGreaterThan(L.character.radius - 0.02);
      }
    }
  });
});

describe("office navigation", () => {
  it("reaches every interaction anchor from the entrance", () => {
    const start: Vec2 = [L.anchors.find((a) => a.id === "Lobby_Entry")!.position[0], L.anchors.find((a) => a.id === "Lobby_Entry")!.position[2]];
    for (const a of L.anchors) {
      if (a.kind === "camera") continue;
      const r = nav.route(start, a.id);
      expect(r, a.id).not.toBeNull();
      expect(r!.length).toBeLessThan(30);
    }
  });

  it("never routes through walls, desks or plants", () => {
    const from = ["Lobby_Entry", "Break_Coffee", "Ops_Inspect", "Research_Reading", "Desk_02_Arrive", "Command_VisitorWait"];
    const to = ["Command_Work", "Desk_05_Seat", "Research_Reading", "Test_Work", "Reporting_Presenter", "Ops_Inspect", "Break_Sofa_Seat",
      "Reporting_Seat_01", "Command_ReceiveReport", "Research_Work", "Lobby_CheckIn"];
    for (const f of from) {
      const fa = index.anchor(f);
      const p: Vec2 = fa.approach ? [fa.approach[0], fa.approach[2]] : [fa.position[0], fa.position[2]];
      for (const t of to) {
        const r = nav.route(p, t)!;
        expect(r, `${f} -> ${t}`).not.toBeNull();
        const goal = index.resolve(t);
        const target = index.anchor(goal.seat ?? goal.id);
        const ignore = new Set(target.ignore ?? []);
        for (let i = 1; i < r.points.length; i++) {
          const last = i === r.points.length - 1;
          const ok = nav.clear(r.points[i - 1], r.points[i], L.clearance - 0.03, last ? ignore : undefined);
          expect(ok, `${f} -> ${t} segment ${i}`).toBe(true);
        }
      }
    }
  });

  it("routes away from every approach point (an Openling leaving a seat or a work spot)", () => {
    const approaches = L.anchors.filter((a) => a.approach && !a.alias);
    for (const a of approaches) {
      const from: Vec2 = [a.approach![0], a.approach![2]];
      for (const to of ["Command_ReceiveReport", "Lobby_Wait", "Break_Sofa_Seat", "Research_Reading"]) {
        if (to === a.id) continue;
        const r = nav.route(from, to);
        expect(r, `${a.id} -> ${to}`).not.toBeNull();
        expect(r!.points.length, `${a.id} -> ${to}`).toBeGreaterThan(1);
      }
    }
  });

  it("covers the required paths between zones", () => {
    const pairs: [string, string][] = [
      ["Lobby_Entry", "Lobby_Wait"], ["Lobby_Entry", "Command_Approach"], ["Lobby_Wait", "Desk_04_Arrive"], ["Desk_04_Arrive", "Reporting_Approach"],
      ["Reporting_Exit", "Command_ReceiveReport"], ["Lobby_Wait", "Research_Exit"], ["Lobby_Wait", "Dev_Exit"], ["Lobby_Wait", "Ops_Exit"],
      ["Lobby_Wait", "Break_Approach"], ["Break_Exit", "Lobby_Wait"],
    ];
    for (const [a, b] of pairs) {
      const pa = index.anchor(a).position;
      expect(nav.route([pa[0], pa[2]], b), `${a} -> ${b}`).not.toBeNull();
    }
  });

  it("wraps angles the short way", () => {
    expect(angleDelta(3, -3)).toBeCloseTo(2 * Math.PI - 6, 6);
    expect(angleDelta(-3, 3)).toBeCloseTo(6 - 2 * Math.PI, 6);
  });
});

describe("status bubbles", () => {
  it("shows no Zzz for idle; Zzz only for sleeping", () => {
    expect(bubbleFor("idle")).toBeNull();
    expect(bubbleFor("sleeping")?.icon).toBe("zzz");
    for (const s of Object.values(STATUS)) if (s.id !== "sleeping") expect(s.icon).not.toBe("zzz");
  });

  it("picks the primary status by priority", () => {
    expect(primaryStatus(["working", "blocked"])).toBe("blocked");
    expect(primaryStatus(["blocked", "human_review"])).toBe("human_review");
    expect(primaryStatus(["waiting", "reporting"])).toBe("reporting");
    expect(primaryStatus(["idle"])).toBe("idle");
    expect(primaryStatus([])).toBe("idle");
  });
});

/** Arrives after a fixed travel time per goal change. */
function stubWorld(sim: () => OfficeSimulation, travel = 6): WorldProbe & { tick(): void } {
  const since = new Map<AgentId, { key: string; t: number }>();
  return {
    tick() {
      const s = sim();
      for (const id of s.agentIds) {
        const g = s.state.agents[id].goal;
        const key = `${g.anchor}/${g.activity}`;
        if (since.get(id)?.key !== key) since.set(id, { key, t: s.t });
      }
    },
    atGoal(agent) {
      const s = sim();
      const e = since.get(agent);
      const g = s.state.agents[agent].goal;
      // a goal set during this step has not been reached yet
      return !!e && e.key === `${g.anchor}/${g.activity}` && s.t - e.t >= travel;
    },
  };
}

function runDemo(seconds: number, setup?: (sim: OfficeSimulation) => void) {
  let sim!: OfficeSimulation;
  const world = stubWorld(() => sim);
  sim = new OfficeSimulation(world);
  setup?.(sim);
  const n = Math.round(seconds / STEP);
  for (let i = 0; i < n; i++) {
    world.tick();
    sim.step();
  }
  return sim;
}

describe("mock agent simulation", () => {
  it("runs the full task lifecycle in order", () => {
    const sim = runDemo(400);
    const types = sim.events.map((e) => e.type);
    const find = (pred: (e: TimedEvent) => boolean) => sim.events.findIndex(pred);
    const created = find((e) => e.type === "task.created");
    const assigned = find((e) => e.type === "task.assigned");
    const coderToDesk = find((e) => e.type === "agent.goal" && e.agent === "coder" && e.anchor === "Desk_05_Seat");
    const coding = find((e) => e.type === "agent.status" && e.agent === "coder" && e.status === "coding");
    const blocked = find((e) => e.type === "task.blocked");
    const opsGo = find((e) => e.type === "agent.goal" && e.agent === "ops" && e.anchor === "Ops_Inspect");
    const unblocked = find((e) => e.type === "task.unblocked");
    const present = find((e) => e.type === "agent.goal" && e.agent === "reporter" && e.anchor === "Reporting_Presenter");
    const toCommander = find((e) => e.type === "agent.goal" && e.agent === "reporter" && e.anchor === "Command_ReceiveReport");
    const wave = find((e) => e.type === "agent.gesture" && e.agent === "commander");
    const done = find((e) => e.type === "task.completed");
    const sleep = find((e) => e.type === "agent.status" && e.agent === "researcher" && e.status === "sleeping");
    const order = [created, assigned, coderToDesk, coding, blocked, opsGo, unblocked, present, toCommander, wave, done, sleep];
    expect(order.every((i) => i >= 0), JSON.stringify(order)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(sim.events.filter((e) => e.type === "task.assigned" && e.taskId === "T1")).toHaveLength(4);
    expect(types.includes("report.delivered")).toBe(true);
    expect(sim.state.completedTasks).toBeGreaterThanOrEqual(1);
  });

  it("is deterministic: the same steps replay the same events", () => {
    const a = runDemo(300).events.map((e) => `${e.t}:${e.type}:${JSON.stringify(e)}`);
    const b = runDemo(300).events.map((e) => `${e.t}:${e.type}:${JSON.stringify(e)}`);
    expect(a).toEqual(b);
  });

  it("only shows Zzz after an explicit sleep, never for idle agents", () => {
    const sim = runDemo(60);
    for (const id of sim.agentIds) expect(sim.state.agents[id].status).not.toBe("sleeping");
  });

  it("Trigger Blocked starts the incident immediately and Ops recovers it", () => {
    const sim = runDemo(30, (s) => s.triggerBlocked());
    expect(sim.events.some((e) => e.type === "alert.raised")).toBe(true);
    expect(sim.events.some((e) => e.type === "agent.goal" && e.agent === "ops" && e.anchor === "Ops_Inspect")).toBe(true);
    expect(sim.events.some((e) => e.type === "alert.cleared")).toBe(true);
  });

  it("Trigger Complete finishes the active subtasks", () => {
    let sim!: OfficeSimulation;
    const world = stubWorld(() => sim);
    sim = new OfficeSimulation(world);
    for (let i = 0; i < Math.round(40 / STEP); i++) { world.tick(); sim.step(); }
    sim.triggerComplete();
    for (let i = 0; i < Math.round(5 / STEP); i++) { world.tick(); sim.step(); }
    const t1 = sim.state.currentTaskId!;
    expect(sim.state.subtasks[`${t1}:code`].status).toBe("completed");
    expect(sim.state.subtasks[`${t1}:research`].status).toBe("completed");
  });

  it("assigns every role and keeps the background workers optional", () => {
    const sim = new OfficeSimulation({ atGoal: () => true }, { workers: false });
    expect(sim.agentIds).toEqual(AGENTS.filter((a) => !a.optional).map((a) => a.id));
    expect(Object.keys(sim.state.agents).sort()).toEqual([...sim.agentIds].sort());
  });
});
