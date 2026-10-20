/**
 * Phase 1.1: agent greetings, the mock conversation and user-assigned tasks on the office simulation.
 */
import { Group, type Object3D } from "three";
import { describe, expect, it } from "vitest";
import { AgentActor } from "../../components/office/runtime/AgentActor";
import type { OpenlingCharacter } from "../../components/openlings/runtime/OpenlingCharacter";
import type { OpenlingClip } from "../openlings/animations";
import type { OpenlingExpression } from "../openlings/expressions";
import type { Loadout } from "../openlings/props";
import type { AgentId } from "./agents";
import { GREETINGS, QUICK_TASKS, checkMessage, classify, interpret, resultMessage, taskTitle } from "./conversation";
import { LayoutIndex, OFFICE_LAYOUT } from "./layout";
import { NavGraph } from "./nav";
import { MAX_QUEUE, OfficeSimulation, STEP, type WorldProbe } from "./simulation";

// ------------------------------------------------------------------ helpers
/** Arrives after a fixed travel time per goal change (as in office.test.ts). */
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
      return !!e && e.key === `${g.anchor}/${g.activity}` && s.t - e.t >= travel;
    },
  };
}

function makeSim() {
  let sim!: OfficeSimulation;
  const world = stubWorld(() => sim);
  sim = new OfficeSimulation(world);
  const run = (seconds: number) => {
    for (let i = 0; i < Math.round(seconds / STEP); i++) {
      world.tick();
      sim.step();
    }
  };
  return { sim, run };
}

function assign(sim: OfficeSimulation, agent: AgentId, text: string, action: "assign" | "replace" = "assign") {
  sim.sendMessage(agent, text);
  const m = [...sim.conversation(agent)].reverse().find((x) => x.proposal);
  expect(m?.proposal?.status, `proposal for "${text}"`).toBe("open");
  expect(sim.answerProposal(agent, m!.id, action)).toBe(true);
  return m!;
}

// ------------------------------------------------------------------ conversation
describe("mock conversation", () => {
  it("classifies requests into task categories with simple keywords", () => {
    expect(classify("Check the login flow.")).toBe("test");
    expect(classify("Research the latest AI trends.")).toBe("research");
    expect(classify("Test the dashboard.")).toBe("test");
    expect(classify("Summarize today's progress.")).toBe("report");
    expect(classify("Inspect system health.")).toBe("ops");
    expect(classify("Build a new feature.")).toBe("code");
    expect(classify("Water the plants")).toBe("general");
  });

  it("turns a request into a short task title", () => {
    expect(taskTitle("Can you test the login page?")).toBe("Test the login page");
    expect(taskTitle("please research the latest AI trends.")).toBe("Research the latest AI trends");
    expect(taskTitle("  hey, could you   build a new feature for me please! ")).toBe("Build a new feature");
    expect(taskTitle("x".repeat(200)).length).toBeLessThanOrEqual(60);
  });

  it("rejects empty and over-long messages", () => {
    expect(checkMessage("   \n ")).toEqual({ ok: false, reason: "empty" });
    expect(checkMessage("a".repeat(281))).toEqual({ ok: false, reason: "too_long" });
    expect(checkMessage("  Check the login flow.  ")).toEqual({ ok: true, text: "Check the login flow." });
  });

  it("answers small talk without inventing work, and proposes a task for a request", () => {
    const ctx = { agent: "coder" as AgentId, name: "Byte", doing: "Idle", activeTask: null, queued: 0 };
    expect(interpret("hi", ctx).kind).toBe("reply");
    expect(interpret("thanks!", ctx).kind).toBe("reply");
    expect(interpret("asdf", ctx).kind).toBe("reply");
    const p = interpret("Can you test the login page?", ctx);
    expect(p.kind).toBe("proposal");
    if (p.kind === "proposal") {
      expect(p.proposal).toMatchObject({ title: "Test the login page", category: "test" });
      expect(p.text).toMatch(/simulated/i);
    }
    expect(interpret('<img src=x onerror="alert(1)">', ctx).kind).toBe("reply"); // markup is never turned into a task
    const busy = interpret("Fix the signup bug", { ...ctx, activeTask: "Build a new feature" });
    expect(busy.kind === "proposal" && /queue/.test(busy.text)).toBe(true);
  });

  it("labels every result as a simulation and never claims real work", () => {
    for (const cat of ["code", "test", "research", "ops", "report", "team", "general"] as const) {
      const r = resultMessage(cat, "X", ["Nova", "Byte"]);
      expect(r, cat).toMatch(/demo|simulat/i);
      expect(r, cat).not.toMatch(/\b(passed|deployed|merged|committed)\b/i);
    }
    expect(resultMessage("test", "Login")).toMatch(/No real test suite was executed/);
  });

  it("has a greeting and three role suggestions for every agent", () => {
    for (const id of Object.keys(GREETINGS) as AgentId[]) {
      expect(GREETINGS[id].length).toBeGreaterThan(5);
      expect(QUICK_TASKS[id]).toHaveLength(3);
    }
  });
});

// ------------------------------------------------------------------ simulation: chat + user tasks
describe("agent chat and user-assigned tasks", () => {
  it("greets once per agent and keeps every conversation separate", () => {
    const { sim } = makeSim();
    sim.openChat("coder");
    sim.openChat("coder");
    expect(sim.conversation("coder").map((m) => m.text)).toEqual([GREETINGS.coder]);
    sim.sendMessage("coder", "hello");
    expect(sim.conversation("tester")).toHaveLength(0);
    sim.openChat("tester");
    expect(sim.conversation("tester").map((m) => m.text)).toEqual([GREETINGS.tester]);
    expect(sim.conversation("coder").every((m) => m.text !== GREETINGS.tester)).toBe(true);
  });

  it("rejects empty submissions without adding a message", () => {
    const { sim } = makeSim();
    expect(sim.sendMessage("coder", "   ").ok).toBe(false);
    expect(sim.conversation("coder")).toHaveLength(0);
  });

  it("runs an assigned task through the existing lifecycle and reports a simulated result", () => {
    const { sim, run } = makeSim();
    run(2);
    assign(sim, "coder", "Can you test the login page?");
    const task = sim.userTasks("coder")[0];
    expect(task).toMatchObject({ title: "Test the login page", category: "test", agentId: "coder" });
    run(0.1);
    expect(sim.userTasks("coder")[0].status).toBe("assigned");
    run(9);
    // walked to its desk, working on it with the matching status and progress
    expect(sim.state.agents.coder.goal).toEqual({ anchor: "Desk_05_Seat", activity: "typing" });
    expect(sim.userTasks("coder")[0].status).toBe("in_progress");
    expect(sim.state.agents.coder.status).toBe("coding");
    run(10);
    expect(sim.userTasks("coder")[0].progress).toBeGreaterThan(0.2);
    run(40);
    const done = sim.userTasks("coder")[0];
    expect(done.status).toBe("completed");
    const result = sim.conversation("coder").find((m) => m.kind === "result");
    expect(result?.text).toMatch(/No real test suite was executed/);
    expect(sim.state.agents.coder.userTaskId).toBeNull();
    const types = sim.events.filter((e) => "taskId" in e && e.taskId === task.id).map((e) => e.type);
    expect(types).toEqual(expect.arrayContaining(["task.requested", "task.started", "task.phase", "task.completed", "task.finished"]));
  });

  it("answers a proposal only once (no double assignment)", () => {
    const { sim } = makeSim();
    const m = assign(sim, "researcher", "Research the latest AI trends");
    expect(sim.answerProposal("researcher", m.id, "assign")).toBe(false);
    expect(sim.userTasks("researcher")).toHaveLength(1);
  });

  it("refuses a duplicate of a queued or active task and caps the queue", () => {
    const { sim } = makeSim();
    expect(sim.quickTask("tester", "tests")?.ok).toBe(true);
    expect(sim.quickTask("tester", "tests")).toEqual({ ok: false, reason: "duplicate" });
    expect(sim.userTasks("tester")).toHaveLength(1);
    for (let i = 0; i < MAX_QUEUE; i++) expect(sim.requestTask("tester", { title: `Task ${i}`, description: "", category: "test" }).ok).toBe(true);
    expect(sim.requestTask("tester", { title: "One too many", description: "", category: "test" })).toEqual({ ok: false, reason: "queue_full" });
  });

  it("queues a second task behind the first, and switches only when asked to", () => {
    const { sim, run } = makeSim();
    assign(sim, "coder", "Build a new feature");
    assign(sim, "coder", "Fix the signup bug");
    run(1);
    const [second, first] = sim.userTasks("coder");
    expect(first.status).toBe("assigned");
    expect(second.status).toBe("queued");
    // an explicit "do it now" sets the current one aside
    assign(sim, "coder", "Review recent code", "replace");
    run(0.2);
    const byTitle = Object.fromEntries(sim.userTasks("coder").map((t) => [t.title, t.status]));
    expect(byTitle["Build a new feature"]).toBe("cancelled");
    expect(byTitle["Review recent code"]).toBe("assigned");
    expect(byTitle["Fix the signup bug"]).toBe("queued");
    // never two tasks in progress on one agent
    run(200);
    const statuses = sim.userTasks("coder").map((t) => t.status);
    expect(statuses.filter((s) => s === "completed")).toHaveLength(2);
    expect(statuses.filter((s) => ["assigned", "in_progress", "reporting", "blocked"].includes(s))).toHaveLength(0);
  });

  it("sets the demo work aside while busy and resumes it afterwards", () => {
    const { sim, run } = makeSim();
    run(1);
    sim.quickTask("researcher", "topic");
    run(8); // the demo delegates and sends the researcher off meanwhile: deferred, not applied
    expect(sim.state.agents.researcher.goal.anchor).toBe("Research_Reading");
    expect(sim.state.agents.researcher.deferred?.goal).toEqual({ anchor: "Research_Reading", activity: "reading" });
    expect(sim.state.agents.researcher.status).not.toBe("idle");
    run(60);
    expect(sim.userTasks("researcher")[0].status).toBe("completed");
    // back on the demo's subtask, which progresses again
    const a = sim.state.agents.researcher;
    expect(a.userTaskId).toBeNull();
    expect(a.subtaskId).toBe("T1:research");
  });

  it("still finishes the demo task when an agent took a user task in between", () => {
    const { sim, run } = makeSim();
    run(3);
    sim.quickTask("coder", "fix");
    run(500);
    expect(sim.state.tasks.T1.status).toBe("completed");
    expect(sim.userTasks("coder")[0].status).toBe("completed");
  });

  it("lets the Tester hit a simulated failure (Worried) and recover", () => {
    const { sim, run } = makeSim();
    sim.quickTask("tester", "ui");
    run(60);
    const ev = sim.events.filter((e) => (e.type === "task.blocked" || e.type === "task.unblocked") && e.subtaskId === "U1:work").map((e) => e.type);
    expect(ev).toEqual(["task.blocked", "task.unblocked"]);
    expect(sim.userTasks("tester")[0].status).toBe("completed");
  });

  it("lets the Commander delegate a team task and report when both parts are done", () => {
    const { sim, run } = makeSim();
    sim.quickTask("commander", "team");
    run(12);
    const kids = sim.state.tasks.U1.children!;
    expect(kids).toHaveLength(2);
    expect(kids.map((id) => sim.state.tasks[id].agent)).toEqual(["researcher", "coder"]);
    expect(sim.conversation("coder").some((m) => m.kind === "info" && /asked me to help/.test(m.text))).toBe(true);
    run(150);
    expect(sim.userTasks("commander")[0].status).toBe("completed");
    expect(sim.conversation("commander").find((m) => m.kind === "result")?.text).toMatch(/Team demo task completed/);
  });

  it("is deterministic with user tasks: the same commands replay the same events", () => {
    const go = () => {
      const { sim, run } = makeSim();
      run(2);
      assign(sim, "coder", "Check the login flow");
      sim.quickTask("ops", "health");
      run(80);
      return sim.events.map((e) => JSON.stringify(e));
    };
    expect(go()).toEqual(go());
  });

  it("pauses with the simulation (no step, no progress) and resets to an empty state", () => {
    const { sim, run } = makeSim();
    sim.quickTask("ops", "health");
    run(10);
    const p = sim.userTasks("ops")[0].progress;
    // no steps while paused: nothing moves
    expect(sim.userTasks("ops")[0].progress).toBe(p);
    const fresh = new OfficeSimulation({ atGoal: () => true });
    expect(fresh.state.queues).toEqual({});
    expect(fresh.state.conversations).toEqual({});
    expect(fresh.userTasks("ops")).toEqual([]);
  });
});

// ------------------------------------------------------------------ greeting on the actor
/** Records what the actor asks of its character (no GLB, no GPU). */
class FakeCharacter {
  readonly root = new Group();
  readonly played: OpenlingClip[] = [];
  readonly gestures: OpenlingClip[] = [];
  expression: OpenlingExpression = "Neutral";
  blink: number | null = null;
  private loadout: Loadout = {};
  clip: OpenlingClip | null = null;
  get state() { return { clip: this.clip, loadout: this.loadout }; }
  play(c: OpenlingClip) { this.played.push(c); this.clip = c; }
  gesture(c: OpenlingClip) { this.gestures.push(c); return 2.6; }
  setExpression(e: OpenlingExpression) { this.expression = e; }
  holdBlink(b: number | null) { this.blink = b; }
  setSpeed() {}
  update() {}
  setLoadout(l: Loadout) { this.loadout = { ...l }; }
  socketFrame(): Object3D | null { return null; }
  dispose() {}
}

function makeActor(id: AgentId) {
  const index = new LayoutIndex(OFFICE_LAYOUT);
  const nav = new NavGraph(index);
  const actors: AgentActor[] = [];
  const ch = new FakeCharacter();
  const actor = new AgentActor(id, ch as unknown as OpenlingCharacter, { index, nav, dynamic: new Map(), actors: () => actors });
  actors.push(actor);
  const step = (seconds: number) => { for (let i = 0; i < Math.round(seconds / STEP); i++) actor.step(STEP); };
  return { actor, ch, step };
}

describe("agent greeting", () => {
  it("turns toward the viewer, waves once with a happy face, turns back and restores its face", () => {
    const { actor, ch, step } = makeActor("ops"); // standing at Ops_Desk, Idle
    const yaw0 = actor.yaw;
    expect(actor.greet(yaw0 + 1)).toBe(true);
    expect(actor.greet(yaw0 + 1)).toBe(false); // no repeated wave while greeting
    step(0.6);
    expect(actor.greetingPhase).toBe("wave");
    expect(ch.played.filter((c) => c === "Wave")).toHaveLength(1);
    expect(ch.expression).toBe("Happy");
    step(4);
    expect(actor.interaction).toBe("normal");
    expect(actor.yaw).toBeCloseTo(yaw0, 3);
    expect(ch.expression).toBe("Neutral"); // idle status face
    expect(ch.clip).toBe("Idle");
    expect(actor.greetings).toBe(1);
  });

  it("restores the activity's own loop after waving (Reporting, not Idle)", () => {
    const { actor, ch, step } = makeActor("commander"); // commanding: Reporting clip
    actor.greet(actor.yaw + 2);
    step(6);
    expect(ch.clip).toBe("Reporting");
  });

  it("waves seated with the arm layer only: no standing up through the desk", () => {
    const { actor, ch, step } = makeActor("worker1"); // typing at Desk_01
    expect(actor.seated).toBe(true);
    const pos = [...actor.pos];
    actor.greet(0); // a facing is ignored when seated
    step(0.1);
    expect(ch.gestures).toEqual(["Wave"]);
    expect(ch.played).not.toContain("Wave");
    expect(ch.played).not.toContain("Idle");
    step(3);
    expect(actor.pos).toEqual(pos);
    expect(actor.seated).toBe(true);
    expect(ch.clip).toBe("Typing");
  });

  it("pauses a walk on its route to greet, then resumes the same trip", () => {
    const { actor, step } = makeActor("coder");
    actor.setGoal({ anchor: "Test_Inspect", activity: "idle" });
    let n = 0;
    while (!actor.onRoute && n++ < 600) actor.step(STEP);
    step(1.5);
    expect(actor.onRoute).toBe(true);
    actor.greet(null);
    step(0.1);
    const held = [...actor.pos];
    step(1.5);
    expect(actor.pos).toEqual(held); // standing still while waving
    step(90);
    expect(actor.atGoalFor({ anchor: "Test_Inspect", activity: "idle" })).toBe(true);
  });

  it("finishes a sit, stand or seat approach before greeting, and a goal set meanwhile waits for the greeting", () => {
    const { actor, ch, step } = makeActor("reporter"); // seated on a stool
    actor.setGoal({ anchor: "Reporting_Presenter", activity: "presenting" });
    actor.step(STEP); // starts standing up
    actor.greet(null);
    step(0.3);
    expect(actor.greetingPhase).toBe("wait"); // still getting up
    let n = 0;
    while (actor.greetingPhase === "wait" && n++ < 600) actor.step(STEP);
    expect(actor.greetingPhase).toBe("wave");
    expect(actor.seated).toBe(false);
    expect(actor.onRoute).toBe(true); // stood up and stepped clear of the stool first
    const at = [...actor.pos];
    step(1);
    expect(actor.pos).toEqual(at);
    step(60);
    expect(actor.atGoalFor({ anchor: "Reporting_Presenter", activity: "presenting" })).toBe(true);
    expect(ch.played.filter((c) => c === "Wave")).toHaveLength(1);
  });

  it("wakes a sleeping Openling to say hi, then lets it sleep again", () => {
    const { actor, ch, step } = makeActor("researcher");
    actor.setGoal({ anchor: "Break_Sofa_Seat", activity: "sleeping" });
    step(120);
    expect(ch.blink).toBe(1);
    actor.greet(null);
    step(0.2);
    expect(ch.blink).toBeNull();
    expect(ch.expression).toBe("Happy");
    step(4);
    expect(ch.blink).toBe(1);
    expect(ch.expression).toBe("Neutral");
  });
});
