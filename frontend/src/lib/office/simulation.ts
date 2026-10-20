/**
 * Deterministic, replayable mock workflow for the Living Office.
 *
 * Three layers, so Phase 2 can swap the mock for real OpenBot events:
 *   OfficeEvent      domain events (task created/assigned/blocked/completed, agent goal/status, alerts)
 *   OfficeState      what the office looks like, built only by applying events (`applyEvent`)
 *   DemoScript       the mock event source: coroutine-like scripts on simulated time that wait
 *                    for arrivals through a WorldProbe (the 3D runtime, or a stub in tests)
 *
 * The simulation advances in fixed steps (STEP seconds of simulated time), so the same
 * sequence of steps always produces the same events: Reset replays the demo exactly.
 *
 * User-assigned tasks (Phase 1.1, from the agent chat) run on the same events and state: each
 * agent has a queue; while it works on one of them it sets its demo work aside (demo goals and
 * statuses for it are deferred) and resumes that work afterwards. Chat history is state too, so
 * Reset clears it with everything else. All of it is local demo data.
 */
import { AGENTS, type Activity, type AgentGoal, type AgentId } from "./agents";
import {
  GREETINGS, QUICK_TASKS, ROLE_CATEGORY, ackMessage, checkMessage, delegatesFor, interpret, resultMessage,
  type MessageCheck, type TaskCategory, type TaskProposal,
} from "./conversation";
import { STATUS, type AgentStatus } from "./status";

export const STEP = 1 / 60;

// ================================================================== events
export type OfficeEvent =
  | { type: "task.created"; taskId: string; title: string; summary: string }
  | { type: "task.assigned"; taskId: string; subtaskId: string; agent: AgentId; title: string; duration: number }
  | { type: "task.progress"; subtaskId: string; progress: number }
  | { type: "task.blocked"; subtaskId: string; agent: AgentId; reason: string }
  | { type: "task.unblocked"; subtaskId: string; agent: AgentId }
  | { type: "subtask.completed"; subtaskId: string; agent: AgentId }
  | { type: "task.completed"; taskId: string }
  | { type: "agent.goal"; agent: AgentId; anchor: string; activity: Activity }
  | { type: "agent.status"; agent: AgentId; status: AgentStatus; detail?: string }
  | { type: "agent.gesture"; agent: AgentId; gesture: "wave" }
  | { type: "alert.raised"; alertId: string; message: string; agent: AgentId }
  | { type: "alert.cleared"; alertId: string }
  | { type: "report.delivered"; taskId: string; from: AgentId; to: AgentId }
  // user-assigned tasks and chat (Phase 1.1)
  | { type: "task.requested"; taskId: string; agent: AgentId; title: string; description: string; category: TaskCategory; by: "user" | AgentId; parent?: string; front?: boolean }
  | { type: "task.started"; taskId: string; subtaskId: string; agent: AgentId; duration: number }
  | { type: "task.phase"; taskId: string; phase: UserTaskPhase }
  | { type: "task.cancelled"; taskId: string; agent: AgentId; reason: string }
  /** The agent is done with its user task; `chain`: another one of its queue starts right away. */
  | { type: "task.finished"; taskId: string; agent: AgentId; chain: boolean }
  | { type: "agent.deferred"; agent: AgentId; goal?: AgentGoal; status?: AgentStatus; detail?: string }
  | { type: "chat.message"; agent: AgentId; messageId: string; from: "user" | "agent"; text: string; kind: ChatKind; taskId?: string; proposal?: TaskProposal }
  | { type: "chat.proposal"; agent: AgentId; messageId: string; resolution: ProposalStatus };

export type TimedEvent = OfficeEvent & { t: number; seq: number };

/** Lifecycle of a user-assigned task. */
export type UserTaskPhase = "queued" | "assigned" | "in_progress" | "blocked" | "reporting" | "completed" | "cancelled";
export type ChatKind = "greeting" | "user" | "reply" | "ack" | "result" | "info";
export type ProposalStatus = "open" | "assigned" | "queued" | "replaced" | "dismissed";

export interface ChatMessage {
  id: string;
  t: number;
  from: "user" | "agent";
  text: string;
  kind: ChatKind;
  taskId?: string;
  proposal?: TaskProposal & { status: ProposalStatus };
}

/** A user-assigned task as the UI shows it (the MockAgentTask contract). */
export interface MockAgentTask {
  id: string;
  agentId: AgentId;
  title: string;
  description: string;
  category: TaskCategory;
  status: UserTaskPhase;
  progress: number;
  createdAt: number;
  by: "user" | AgentId;
}

// ================================================================== state
export interface AgentState {
  id: AgentId;
  name: string;
  roleLabel: string;
  status: AgentStatus;
  /** Status to fall back to when a transient status (Completed) expires. */
  baseStatus: AgentStatus;
  statusUntil: number | null;
  detail: string;
  goal: AgentGoal;
  subtaskId: string | null;
  recent: { t: number; text: string }[];
  gestureSeq: number;
  gesture: "wave" | null;
  /** The user-assigned task this agent works on now (its demo work is set aside meanwhile). */
  userTaskId: string | null;
  /** The demo work set aside: goal, status and subtask to go back to when the user tasks are done. */
  resume: { goal: AgentGoal; status: AgentStatus; detail: string; subtaskId: string | null } | null;
  /** Demo goal / status asked for while the agent was busy with a user task (applied when it ends). */
  deferred: { goal?: AgentGoal; status?: AgentStatus; detail?: string } | null;
}

export interface SubtaskState {
  id: string;
  taskId: string;
  title: string;
  agent: AgentId;
  progress: number;
  duration: number;
  status: "active" | "blocked" | "completed" | "cancelled";
}

export interface TaskState {
  id: string;
  title: string;
  summary: string;
  status: "active" | "blocked" | "completed" | "cancelled";
  createdAt: number;
  completedAt: number | null;
  subtasks: string[];
  /** "user": assigned from the chat (or delegated by the Commander for one); "demo": the scripted workflow. */
  source: "demo" | "user";
  agent?: AgentId;
  category?: TaskCategory;
  phase?: UserTaskPhase;
  by?: "user" | AgentId;
  parent?: string;
  children?: string[];
}

export interface OfficeState {
  t: number;
  agents: Record<AgentId, AgentState>;
  tasks: Record<string, TaskState>;
  subtasks: Record<string, SubtaskState>;
  taskOrder: string[];
  currentTaskId: string | null;
  alerts: { id: string; message: string; agent: AgentId; t: number }[];
  log: { t: number; text: string; agent?: AgentId; kind: "task" | "status" | "alert" | "move" | "report" }[];
  completedTasks: number;
  /** User-assigned tasks waiting per agent, oldest first. */
  queues: Partial<Record<AgentId, string[]>>;
  conversations: Partial<Record<AgentId, ChatMessage[]>>;
}

export function initialState(): OfficeState {
  const agents = {} as Record<AgentId, AgentState>;
  for (const p of AGENTS) {
    agents[p.id] = {
      id: p.id, name: p.name, roleLabel: p.roleLabel, status: p.start.activity === "typing" ? "working" : "idle",
      baseStatus: p.start.activity === "typing" ? "working" : "idle", statusUntil: null, detail: "", goal: { ...p.start }, subtaskId: null,
      recent: [], gestureSeq: 0, gesture: null, userTaskId: null, resume: null, deferred: null,
    };
  }
  return { t: 0, agents, tasks: {}, subtasks: {}, taskOrder: [], currentTaskId: null, alerts: [], log: [], completedTasks: 0, queues: {}, conversations: {} };
}

const MAX_LOG = 60;
const MAX_RECENT = 6;
const MAX_CHAT = 80;
/** User tasks an agent keeps waiting at most (besides the one it works on). */
export const MAX_QUEUE = 3;

function note(s: OfficeState, text: string, kind: OfficeState["log"][number]["kind"], agent?: AgentId) {
  s.log.push({ t: s.t, text, agent, kind });
  if (s.log.length > MAX_LOG) s.log.shift();
  if (agent) {
    const a = s.agents[agent];
    a.recent.push({ t: s.t, text });
    if (a.recent.length > MAX_RECENT) a.recent.shift();
  }
}

/** Applies one event to the state (mutates it). The only way the office state changes. */
export function applyEvent(s: OfficeState, e: OfficeEvent): void {
  switch (e.type) {
    case "task.created":
      s.tasks[e.taskId] = { id: e.taskId, title: e.title, summary: e.summary, status: "active", createdAt: s.t, completedAt: null, subtasks: [], source: "demo" };
      s.taskOrder.push(e.taskId);
      s.currentTaskId = e.taskId;
      note(s, `New task: ${e.title}`, "task");
      break;
    case "task.assigned": {
      s.subtasks[e.subtaskId] = { id: e.subtaskId, taskId: e.taskId, title: e.title, agent: e.agent, progress: 0, duration: e.duration, status: "active" };
      s.tasks[e.taskId]?.subtasks.push(e.subtaskId);
      const a = s.agents[e.agent];
      // busy with a user task: the demo subtask waits with the rest of its set-aside work
      if (a.userTaskId && a.resume) a.resume.subtaskId = e.subtaskId;
      else a.subtaskId = e.subtaskId;
      note(s, `Assigned: ${e.title}`, "task", e.agent);
      break;
    }
    case "task.progress": {
      const st = s.subtasks[e.subtaskId];
      if (st && st.status !== "completed") st.progress = Math.min(1, e.progress);
      break;
    }
    case "task.blocked": {
      const st = s.subtasks[e.subtaskId];
      if (st) st.status = "blocked";
      const task = st && s.tasks[st.taskId];
      if (task) task.status = "blocked";
      if (task?.source === "user") task.phase = "blocked";
      note(s, `Blocked: ${e.reason}`, "alert", e.agent);
      break;
    }
    case "task.unblocked": {
      const st = s.subtasks[e.subtaskId];
      if (st && st.status === "blocked") st.status = "active";
      const task = st && s.tasks[st.taskId];
      if (task && task.status === "blocked") task.status = "active";
      if (task?.source === "user" && task.phase === "blocked") task.phase = "in_progress";
      note(s, "Unblocked: back to work", "status", e.agent);
      break;
    }
    case "subtask.completed": {
      const st = s.subtasks[e.subtaskId];
      if (st) { st.status = "completed"; st.progress = 1; }
      note(s, `Done: ${st?.title ?? e.subtaskId}`, "task", e.agent);
      break;
    }
    case "task.completed": {
      const task = s.tasks[e.taskId];
      if (task && task.status !== "completed") {
        task.status = "completed";
        task.completedAt = s.t;
        if (task.source === "user") task.phase = "completed";
        s.completedTasks++;
        note(s, `Task completed: ${task.title}`, "task");
      }
      break;
    }
    case "agent.goal": {
      const a = s.agents[e.agent];
      a.goal = { anchor: e.anchor, activity: e.activity };
      note(s, `Heading to ${anchorLabel(e.anchor)}`, "move", e.agent);
      break;
    }
    case "agent.status": {
      const a = s.agents[e.agent];
      const info = STATUS[e.status];
      if (info.transient) {
        a.statusUntil = s.t + info.transient;
      } else {
        a.baseStatus = e.status;
        a.statusUntil = null;
      }
      a.status = e.status;
      a.detail = e.detail ?? info.label;
      note(s, e.detail ?? info.label, "status", e.agent);
      break;
    }
    case "agent.gesture": {
      const a = s.agents[e.agent];
      a.gesture = e.gesture;
      a.gestureSeq++;
      break;
    }
    case "alert.raised":
      s.alerts.push({ id: e.alertId, message: e.message, agent: e.agent, t: s.t });
      note(s, `Alert: ${e.message}`, "alert", e.agent);
      break;
    case "alert.cleared":
      s.alerts = s.alerts.filter((x) => x.id !== e.alertId);
      note(s, "Alert cleared", "alert");
      break;
    case "report.delivered":
      note(s, `Report delivered to ${s.agents[e.to].name}`, "report", e.from);
      break;
    case "task.requested": {
      s.tasks[e.taskId] = {
        id: e.taskId, title: e.title, summary: e.description, status: "active", createdAt: s.t, completedAt: null, subtasks: [], source: "user",
        agent: e.agent, category: e.category, phase: "queued", by: e.by, parent: e.parent, children: [],
      };
      s.taskOrder.push(e.taskId);
      if (e.parent) s.tasks[e.parent]?.children?.push(e.taskId);
      const q = (s.queues[e.agent] ??= []);
      if (e.front) q.unshift(e.taskId); else q.push(e.taskId);
      note(s, `Task from ${e.by === "user" ? "you" : s.agents[e.by]?.name ?? e.by}: ${e.title}`, "task", e.agent);
      break;
    }
    case "task.started": {
      const task = s.tasks[e.taskId];
      const a = s.agents[e.agent];
      s.queues[e.agent] = (s.queues[e.agent] ?? []).filter((id) => id !== e.taskId);
      s.subtasks[e.subtaskId] = { id: e.subtaskId, taskId: e.taskId, title: task.title, agent: e.agent, progress: 0, duration: e.duration, status: "active" };
      task.subtasks.push(e.subtaskId);
      task.phase = "assigned";
      // remember the demo work only once: a chain of user tasks goes back to what came before the first
      a.resume ??= { goal: { ...a.goal }, status: a.baseStatus, detail: a.statusUntil === null ? a.detail : STATUS[a.baseStatus].label, subtaskId: a.subtaskId };
      a.userTaskId = e.taskId;
      a.subtaskId = e.subtaskId;
      note(s, `Started: ${task.title}`, "task", e.agent);
      break;
    }
    case "task.phase": {
      const task = s.tasks[e.taskId];
      if (task) task.phase = e.phase;
      break;
    }
    case "task.cancelled": {
      const task = s.tasks[e.taskId];
      if (!task || task.status === "completed" || task.status === "cancelled") break;
      task.status = "cancelled";
      task.phase = "cancelled";
      for (const id of task.subtasks) if (s.subtasks[id].status !== "completed") s.subtasks[id].status = "cancelled";
      s.queues[e.agent] = (s.queues[e.agent] ?? []).filter((id) => id !== e.taskId);
      const a = s.agents[e.agent];
      if (a.userTaskId === e.taskId) {
        a.userTaskId = null;
        a.subtaskId = a.resume?.subtaskId ?? null;
      }
      note(s, `Set aside: ${task.title} (${e.reason})`, "task", e.agent);
      break;
    }
    case "task.finished": {
      const a = s.agents[e.agent];
      if (a.userTaskId === e.taskId) a.userTaskId = null;
      a.subtaskId = a.resume?.subtaskId ?? null;
      if (!e.chain) {
        a.resume = null;
        a.deferred = null;
      }
      break;
    }
    case "agent.deferred": {
      const a = s.agents[e.agent];
      a.deferred = { ...a.deferred };
      if (e.goal) a.deferred.goal = { ...e.goal };
      if (e.status) {
        a.deferred.status = e.status;
        a.deferred.detail = e.detail;
      }
      break;
    }
    case "chat.message": {
      const list = (s.conversations[e.agent] ??= []);
      list.push({
        id: e.messageId, t: s.t, from: e.from, text: e.text, kind: e.kind, taskId: e.taskId,
        proposal: e.proposal ? { ...e.proposal, status: "open" } : undefined,
      });
      if (list.length > MAX_CHAT) list.shift();
      break;
    }
    case "chat.proposal": {
      const m = s.conversations[e.agent]?.find((x) => x.id === e.messageId);
      if (m?.proposal) m.proposal.status = e.resolution;
      break;
    }
  }
}

/** Expires transient statuses (Completed falls back to the agent's underlying status). */
export function expireStatuses(s: OfficeState): void {
  for (const a of Object.values(s.agents)) {
    if (a.statusUntil !== null && s.t >= a.statusUntil) {
      a.status = a.baseStatus;
      a.statusUntil = null;
      a.detail = STATUS[a.baseStatus].label;
    }
  }
}

const ANCHOR_LABELS: Record<string, string> = {
  Command_Work: "the Command Hub", Command_ReceiveReport: "the Commander", Command_VisitorWait: "the Command Hub",
  Research_Reading: "the Research Corner", Research_Work: "the research desk", Research_Discuss: "the Research Corner",
  Test_Work: "the test bay", Test_Inspect: "the test bay", Ops_Inspect: "the Ops Wall", Ops_AlertReview: "the Ops Wall", Ops_Desk: "the Ops desk",
  Reporting_Presenter: "the Reporting Area", Reporting_Seat_01: "the Reporting Area", Reporting_Seat_02: "the Reporting Area",
  Break_Sofa_Seat: "the Break Area", Break_Sofa_Seat_2: "the Break Area", Break_Coffee: "the coffee station", Break_Chair_Seat: "the Break Area",
  Lobby_Wait: "the lobby", Lobby_CheckIn: "the lobby",
};

export function anchorLabel(id: string): string {
  if (ANCHOR_LABELS[id]) return ANCHOR_LABELS[id];
  const m = /^Desk_(\d+)/.exec(id);
  if (m) return `desk ${Number(m[1])}`;
  if (id.startsWith("Dev_Desk")) return "the dev lab";
  return id.replace(/_/g, " ");
}

// ================================================================== world probe
/** What the script may ask the 3D world (or a test stub). */
export interface WorldProbe {
  /** The agent stands (or sits) at its current goal anchor and performs its activity. */
  atGoal(agent: AgentId): boolean;
}

// ================================================================== script engine
type Cond = (sim: OfficeSimulation) => boolean;
type Step =
  | { kind: "wait"; seconds: number }
  | { kind: "until"; cond: Cond; timeout?: number }
  | { kind: "do"; run: (sim: OfficeSimulation) => void };

interface Runner {
  name: string;
  steps: Step[];
  pc: number;
  timer: number;
  loop: boolean;
}

const wait = (seconds: number): Step => ({ kind: "wait", seconds });
const until = (cond: Cond, timeout?: number): Step => ({ kind: "until", cond, timeout });
const run = (fn: (sim: OfficeSimulation) => void): Step => ({ kind: "do", run: fn });

const TASKS = [
  { title: "Weekly insights report", summary: "Gather signals, build the pipeline, validate it and present the findings." },
  { title: "Customer feedback digest", summary: "Cluster this week's feedback, ship the digest job, check it and brief the team." },
  { title: "Release readiness check", summary: "Review the changes, run the checks, fix what fails and report go / no-go." },
];

/** Simulated time each subtask needs while its agent works at the goal. */
const DURATION = { research: 26, code: 30, test: 36, report: 9 };

/** Where and how each agent works on a user-assigned task (its role's own workplace and activity). */
interface WorkPlan { anchor: string; activity: Activity; status: AgentStatus; duration: number }
const WORK: Record<AgentId, WorkPlan> = {
  commander: { anchor: "Command_Work", activity: "commanding", status: "working", duration: 0 },
  coder: { anchor: "Desk_05_Seat", activity: "typing", status: "coding", duration: 22 },
  researcher: { anchor: "Research_Reading", activity: "reading", status: "thinking", duration: 20 },
  tester: { anchor: "Test_Work", activity: "testing", status: "testing", duration: 22 },
  ops: { anchor: "Ops_Inspect", activity: "inspecting", status: "working", duration: 16 },
  reporter: { anchor: "Reporting_Presenter", activity: "presenting", status: "reporting", duration: 14 },
  worker1: { anchor: "Desk_01_Seat", activity: "typing", status: "coding", duration: 20 },
  worker2: { anchor: "Desk_03_Seat", activity: "typing", status: "coding", duration: 20 },
};
const VERB: Record<TaskCategory, string> = {
  code: "Building", test: "Checking", research: "Researching", ops: "Inspecting", report: "Summarizing", team: "Coordinating", general: "Working on",
};
/** The part of a team task each delegate takes. */
const PART: Partial<Record<AgentId, string>> = { coder: "Build", tester: "Check", researcher: "Research", reporter: "Write-up", ops: "System check" };

export type AssignResult = { ok: true; taskId: string; queuedBehind: number } | { ok: false; reason: "duplicate" | "queue_full" | "unknown_agent" };

export interface SimulationOptions {
  /** Include the two background workers (Kit, Mo). */
  workers?: boolean;
}

export class OfficeSimulation {
  readonly state: OfficeState;
  readonly events: TimedEvent[] = [];
  private seq = 0;
  private runners: Runner[] = [];
  private probe: WorldProbe;
  private cycle = 0;
  private incident: { active: boolean; done: boolean } = { active: false, done: false };
  private reportRunning = false;
  private reportDone = false;
  private listeners = new Set<(e: TimedEvent) => void>();
  readonly agentIds: AgentId[];

  constructor(probe: WorldProbe, options: SimulationOptions = {}) {
    this.probe = probe;
    this.state = initialState();
    this.agentIds = AGENTS.filter((a) => options.workers !== false || !a.optional).map((a) => a.id);
    if (options.workers === false) {
      for (const a of AGENTS) if (a.optional) delete (this.state.agents as Partial<Record<AgentId, AgentState>>)[a.id];
    }
    this.runners.push({ name: "main", steps: this.mainScript(), pc: 0, timer: 0, loop: true });
  }

  get t(): number {
    return this.state.t;
  }

  setProbe(p: WorldProbe) {
    this.probe = p;
  }

  onEvent(fn: (e: TimedEvent) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Emits a domain event: stamps it, applies it to the state, records and broadcasts it. */
  emit(e: OfficeEvent) {
    const te = { ...e, t: this.state.t, seq: this.seq++ } as TimedEvent;
    applyEvent(this.state, e);
    this.events.push(te);
    if (this.events.length > 400) this.events.shift();
    for (const fn of this.listeners) fn(te);
  }

  has(agent: AgentId): boolean {
    return this.agentIds.includes(agent);
  }

  /**
   * The agent stands at the goal the demo script set it. False while the agent works on a user task:
   * the demo waits for it (with its timeouts) and its subtask does not progress meanwhile.
   */
  atGoal(agent: AgentId): boolean {
    return !this.busyWithUser(agent) && this.probe.atGoal(agent);
  }

  /** Works on a user-assigned task right now. */
  busyWithUser(agent: AgentId): boolean {
    return !!this.state.agents[agent]?.userTaskId;
  }

  /** Advances simulated time by exactly one fixed step. */
  step() {
    const s = this.state;
    s.t = Math.round((s.t + STEP) * 1e6) / 1e6;
    expireStatuses(s);
    this.tickProgress();
    for (const r of [...this.runners]) this.tickRunner(r);
    this.runners = this.runners.filter((r) => r.pc < r.steps.length || r.loop);
  }

  /** Advances by `seconds` of simulated time in fixed steps. */
  advance(seconds: number) {
    const n = Math.round(seconds / STEP);
    for (let i = 0; i < n; i++) this.step();
  }

  private tickRunner(r: Runner) {
    // run as many instantaneous steps as possible in one tick
    for (let guard = 0; guard < 64; guard++) {
      if (r.pc >= r.steps.length) {
        if (!r.loop) return;
        r.pc = 0;
        r.steps = this.mainScript();
      }
      const st = r.steps[r.pc];
      if (st.kind === "do") {
        st.run(this);
        r.pc++;
        r.timer = 0;
        continue;
      }
      r.timer += STEP;
      if (st.kind === "wait") {
        if (r.timer + 1e-9 >= st.seconds) { r.pc++; r.timer = 0; continue; }
        return;
      }
      if (st.cond(this) || (st.timeout !== undefined && r.timer >= st.timeout)) { r.pc++; r.timer = 0; continue; }
      return;
    }
  }

  /**
   * Subtasks progress while their agent works on them at its goal and nothing blocks them (an agent
   * works on one subtask at a time). A Commander's team task progresses with its delegates' parts.
   */
  private tickProgress() {
    const s = this.state;
    for (const st of Object.values(s.subtasks)) {
      if (st.status !== "active" || !this.has(st.agent)) continue;
      const children = s.tasks[st.taskId]?.children;
      if (children?.length) {
        st.progress = children.reduce((sum, id) => sum + this.taskProgress(id), 0) / children.length;
        continue;
      }
      const a = s.agents[st.agent];
      if (a.subtaskId !== st.id || !this.probe.atGoal(st.agent)) continue;
      const working = ["coding", "testing", "working", "thinking", "reporting"].includes(a.baseStatus);
      if (!working) continue;
      st.progress = Math.min(1, st.progress + STEP / st.duration);
    }
  }

  private taskProgress(taskId: string): number {
    const t = this.state.tasks[taskId];
    if (!t) return 0;
    if (t.status === "completed" || t.status === "cancelled") return 1;
    return t.subtasks.length ? this.state.subtasks[t.subtasks[t.subtasks.length - 1]].progress : 0;
  }

  progress(subtask: string): number {
    return this.state.subtasks[subtask]?.progress ?? 0;
  }

  // ------------------------------------------------------------- helpers used by scripts
  /** Sets an agent's goal. Demo goals for an agent busy with a user task wait until it is done. */
  goal(agent: AgentId, anchor: string, activity: Activity, source: "demo" | "user" = "demo") {
    if (!this.has(agent)) return;
    if (source === "demo" && this.busyWithUser(agent)) {
      this.emit({ type: "agent.deferred", agent, goal: { anchor, activity } });
      return;
    }
    const g = this.state.agents[agent].goal;
    if (g.anchor === anchor && g.activity === activity) return;
    this.emit({ type: "agent.goal", agent, anchor, activity });
  }

  /** Sets an agent's status. Demo statuses for an agent busy with a user task wait (transient ones are dropped). */
  status(agent: AgentId, status: AgentStatus, detail?: string, source: "demo" | "user" = "demo") {
    if (!this.has(agent)) return;
    if (source === "demo" && this.busyWithUser(agent)) {
      if (!STATUS[status].transient) this.emit({ type: "agent.deferred", agent, status, detail });
      return;
    }
    this.emit({ type: "agent.status", agent, status, detail });
  }

  private sub(kind: keyof typeof DURATION) {
    return `${this.state.currentTaskId}:${kind}`;
  }

  private complete(kind: keyof typeof DURATION, agent: AgentId) {
    const id = this.sub(kind);
    const st = this.state.subtasks[id];
    if (!st || st.status === "completed") return;
    this.emit({ type: "subtask.completed", subtaskId: id, agent });
  }

  // ------------------------------------------------------------- the main demo loop
  private mainScript(): Step[] {
    const task = TASKS[this.cycle % TASKS.length];
    const taskId = `T${this.cycle + 1}`;
    const steps: Step[] = [
      run((sim) => {
        sim.reportDone = false;
        sim.incident = { active: false, done: false };
      }),
      wait(this.cycle === 0 ? 1.5 : 4),
      // Step 1: a new task reaches the Commander
      run((sim) => {
        sim.emit({ type: "task.created", taskId, title: task.title, summary: task.summary });
        sim.status("commander", "thinking", "Planning the task");
      }),
      wait(4),
      // Step 2: delegation
      run((sim) => {
        sim.status("commander", "working", "Delegating subtasks");
        sim.emit({ type: "task.assigned", taskId, subtaskId: `${taskId}:research`, agent: "researcher", title: "Research the signals", duration: DURATION.research });
        sim.emit({ type: "task.assigned", taskId, subtaskId: `${taskId}:code`, agent: "coder", title: "Build the pipeline", duration: DURATION.code });
        sim.emit({ type: "task.assigned", taskId, subtaskId: `${taskId}:test`, agent: "tester", title: "Validate the results", duration: DURATION.test });
        sim.emit({ type: "task.assigned", taskId, subtaskId: `${taskId}:report`, agent: "reporter", title: "Present the findings", duration: DURATION.report });
        sim.status("coder", "thinking", "Reading the brief");
        sim.status("researcher", "thinking", "Planning the research");
      }),
      wait(2.5),
      // Step 3: movement to the work areas
      run((sim) => {
        sim.goal("coder", "Desk_05_Seat", "typing");
        sim.goal("researcher", "Research_Reading", "reading");
        sim.goal("tester", "Test_Work", "testing");
        sim.status("commander", "waiting", "Monitoring progress");
      }),
      // Step 4: parallel execution
      until((sim) => sim.atGoal("coder"), 90),
      run((sim) => sim.status("coder", "coding", "Coding the pipeline")),
      until((sim) => sim.atGoal("researcher"), 90),
      run((sim) => sim.status("researcher", "thinking", "Researching market signals")),
      until((sim) => sim.atGoal("tester"), 60),
      run((sim) => sim.status("tester", "testing", "Running integration tests")),
      // Step 5/6: a mock failure (unless the Blocked trigger already ran one this cycle)
      until((sim) => sim.progress(`${taskId}:test`) >= 0.3, 60),
      run((sim) => { if (!sim.incident.done && !sim.incident.active) sim.startIncident(); }),
      until((sim) => !sim.incident.active, 120),
      // Step 7: research and code complete
      until((sim) => sim.progress(`${taskId}:code`) >= 1 && sim.progress(`${taskId}:research`) >= 1, 120),
      run((sim) => {
        sim.complete("code", "coder");
        sim.complete("research", "researcher");
        sim.status("coder", "completed", "Pipeline built");
        sim.status("researcher", "completed", "Signals collected");
        sim.status("reporter", "working", "Collecting the results");
        sim.goal("coder", "Desk_05_Seat", "seated");
      }),
      until((sim) => sim.progress(`${taskId}:test`) >= 1, 90),
      run((sim) => {
        sim.complete("test", "tester");
        sim.status("tester", "completed", "All checks pass");
        sim.goal("researcher", "Research_Discuss", "idle");
      }),
      wait(1.5),
      // Step 8 + 9: report (unless the Report trigger already ran it)
      run((sim) => { if (!sim.reportRunning && !sim.reportDone) sim.startReport(); }),
      until((sim) => sim.reportDone, 180),
      wait(2),
      // Step 10: rest
      run((sim) => {
        sim.goal("researcher", "Break_Sofa_Seat", "resting");
        sim.status("researcher", "resting", "Taking a break");
        sim.status("coder", "idle");
        sim.status("tester", "idle");
        sim.goal("tester", "Test_Inspect", "idle");
      }),
      until((sim) => sim.atGoal("researcher"), 90),
      wait(5),
      run((sim) => {
        sim.goal("researcher", "Break_Sofa_Seat", "sleeping");
        sim.status("researcher", "sleeping", "Recharging");
      }),
      wait(12),
      // back to normal office activity
      run((sim) => {
        sim.status("researcher", "idle", "Back to work");
        sim.goal("researcher", "Command_VisitorWait", "waiting");
        sim.goal("reporter", "Reporting_Seat_01", "seated");
        sim.status("reporter", "waiting", "Ready for the next report");
        sim.goal("coder", "Break_Coffee", "coffee");
        sim.status("commander", "idle", "Ready for the next task");
        sim.cycle++;
      }),
      until((sim) => sim.atGoal("researcher") && sim.atGoal("coder"), 90),
    ];
    return steps;
  }

  /** Blocked event and recovery: the Tester hits a failure, Ops inspects the Ops Wall and fixes it. */
  startIncident() {
    if (this.incident.active) return;
    this.incident = { active: true, done: false };
    const taskId = this.state.currentTaskId;
    const alertId = `A${this.seq}`;
    const steps: Step[] = [
      run((sim) => {
        if (taskId && sim.state.subtasks[`${taskId}:test`]) sim.emit({ type: "task.blocked", subtaskId: `${taskId}:test`, agent: "tester", reason: "Integration test failed: schema mismatch" });
        sim.status("tester", "blocked", "Tests failing: schema mismatch");
        sim.emit({ type: "alert.raised", alertId, message: "Data pipeline check failed", agent: "tester" });
        sim.status("ops", "blocked", "Alert received");
      }),
      wait(2),
      run((sim) => sim.goal("ops", "Ops_Inspect", "inspecting")),
      until((sim) => sim.atGoal("ops"), 60),
      run((sim) => sim.status("ops", "working", "Inspecting the Ops Wall")),
      wait(6),
      run((sim) => {
        sim.emit({ type: "alert.cleared", alertId });
        if (taskId && sim.state.subtasks[`${taskId}:test`]) sim.emit({ type: "task.unblocked", subtaskId: `${taskId}:test`, agent: "tester" });
        sim.status("tester", "testing", "Re-running the tests");
        sim.status("ops", "completed", "Schema fixed");
      }),
      wait(3),
      run((sim) => {
        sim.status("ops", "idle");
        sim.goal("ops", "Ops_Desk", "idle");
        sim.incident = { active: false, done: true };
      }),
    ];
    this.runners.push({ name: "incident", steps, pc: 0, timer: 0, loop: false });
  }

  /** The Reporter presents in the Reporting Area, then reports to the Commander. */
  startReport() {
    if (this.reportRunning) return;
    this.reportRunning = true;
    const taskId = this.state.currentTaskId;
    const steps: Step[] = [
      run((sim) => {
        sim.goal("reporter", "Reporting_Presenter", "presenting");
        sim.status("reporter", "reporting", "Preparing the report");
      }),
      until((sim) => sim.atGoal("reporter"), 90),
      run((sim) => sim.status("reporter", "reporting", "Presenting the findings")),
      wait(9),
      run((sim) => {
        sim.goal("reporter", "Command_ReceiveReport", "reporting");
        sim.status("reporter", "reporting", "Reporting to the Commander");
      }),
      until((sim) => sim.atGoal("reporter"), 90),
      wait(1.2),
      run((sim) => {
        sim.emit({ type: "agent.gesture", agent: "commander", gesture: "wave" });
        sim.status("commander", "completed", "Report received");
        if (taskId) {
          sim.emit({ type: "report.delivered", taskId, from: "reporter", to: "commander" });
          if (sim.state.subtasks[`${taskId}:report`]) sim.emit({ type: "subtask.completed", subtaskId: `${taskId}:report`, agent: "reporter" });
        }
      }),
      wait(3),
      run((sim) => {
        if (taskId) sim.emit({ type: "task.completed", taskId });
        sim.status("reporter", "completed", "Task delivered");
        sim.goal("reporter", "Reporting_Seat_01", "seated");
        sim.reportRunning = false;
        sim.reportDone = true;
      }),
    ];
    this.runners.push({ name: "report", steps, pc: 0, timer: 0, loop: false });
  }

  // ------------------------------------------------------------- user tasks (Phase 1.1)
  private userSeq = 0;
  private messageSeq = 0;

  /** Queues a user task for an agent (it starts right away when the agent has none in progress). */
  requestTask(agent: AgentId, p: TaskProposal, opts: { by?: "user" | AgentId; parent?: string; front?: boolean } = {}): AssignResult {
    if (!this.has(agent)) return { ok: false, reason: "unknown_agent" };
    const s = this.state;
    const a = s.agents[agent];
    const queue = s.queues[agent] ?? [];
    const same = (id: string | null | undefined) => !!id && s.tasks[id]?.title.toLowerCase() === p.title.toLowerCase();
    if (same(a.userTaskId) || queue.some(same)) return { ok: false, reason: "duplicate" };
    if (queue.length >= MAX_QUEUE) return { ok: false, reason: "queue_full" };
    const taskId = `U${++this.userSeq}`;
    const queuedBehind = (a.userTaskId ? 1 : 0) + (opts.front ? 0 : queue.length);
    this.emit({ type: "task.requested", taskId, agent, title: p.title, description: p.description, category: p.category, by: opts.by ?? "user", parent: opts.parent, front: opts.front });
    this.startNextUserTask(agent);
    return { ok: true, taskId, queuedBehind };
  }

  /** Sets the agent's current user task aside (on purpose: the user asked to switch). */
  private cancelActive(agent: AgentId, reason: string) {
    const id = this.state.agents[agent].userTaskId;
    if (!id) return;
    this.runners = this.runners.filter((r) => r.name !== `user:${agent}`);
    this.emit({ type: "task.cancelled", taskId: id, agent, reason });
  }

  /** Starts the agent's next queued task now (so queue positions are exact), then runs its script. */
  private startNextUserTask(agent: AgentId) {
    const a = this.state.agents[agent];
    const next = (this.state.queues[agent] ?? [])[0];
    if (a.userTaskId || !next || this.runners.some((r) => r.name === `user:${agent}`)) return;
    const team = agent === "commander";
    this.emit({ type: "task.started", taskId: next, subtaskId: `${next}:work`, agent, duration: team ? 1 : WORK[agent].duration });
    this.status(agent, "thinking", team ? `Planning: ${this.state.tasks[next].title}` : "Reading the request", "user");
    const steps = team ? this.teamTaskScript(next) : this.userTaskScript(agent, next);
    this.runners.push({ name: `user:${agent}`, steps, pc: 0, timer: 0, loop: false });
  }

  /** One agent works through one user task at its role's workplace, then reports the (simulated) result. */
  private userTaskScript(agent: AgentId, taskId: string): Step[] {
    const plan = WORK[agent];
    const task = this.state.tasks[taskId];
    const title = task.title;
    const subtaskId = `${taskId}:work`;
    const verb = VERB[task.category === "general" ? ROLE_CATEGORY[agent] : task.category!];
    const steps: Step[] = [
      wait(1.2),
      run((sim) => {
        sim.goal(agent, plan.anchor, plan.activity, "user");
        sim.status(agent, "thinking", `On my way to ${anchorLabel(plan.anchor)}`, "user");
      }),
      until((sim) => sim.probe.atGoal(agent), 90),
      run((sim) => {
        sim.emit({ type: "task.phase", taskId, phase: "in_progress" });
        sim.status(agent, plan.status, `${verb}: ${title}`, "user");
      }),
    ];
    if (agent === "tester") {
      // the Tester's checks hit one simulated flaky failure (Worried), then pass on the re-run
      steps.push(
        until((sim) => sim.progress(subtaskId) >= 0.45, 120),
        run((sim) => {
          sim.emit({ type: "task.blocked", subtaskId, agent, reason: "A simulated check failed" });
          sim.status(agent, "blocked", "Simulated failure: re-checking", "user");
        }),
        wait(3.5),
        run((sim) => {
          sim.emit({ type: "task.unblocked", subtaskId, agent });
          sim.status(agent, plan.status, `Re-running: ${title}`, "user");
        }),
      );
    }
    steps.push(
      until((sim) => sim.progress(subtaskId) >= 1, plan.duration * 4),
      run((sim) => {
        sim.emit({ type: "task.phase", taskId, phase: "reporting" });
        sim.status(agent, "reporting", "Writing up the result", "user");
      }),
      wait(2.5),
      run((sim) => sim.finishUserTask(agent, taskId, resultMessage(task.category!, title))),
    );
    return steps;
  }

  /** The Commander splits a team task between two delegates, waits for both, then reports. */
  private teamTaskScript(taskId: string): Step[] {
    const task = this.state.tasks[taskId];
    const title = task.title;
    const delegates = delegatesFor(task.category!).filter((d) => this.has(d));
    const kids: string[] = [];
    return [
      wait(1.2),
      run((sim) => sim.goal("commander", WORK.commander.anchor, WORK.commander.activity, "user")),
      until((sim) => sim.probe.atGoal("commander"), 60),
      run((sim) => {
        sim.emit({ type: "task.phase", taskId, phase: "in_progress" });
        sim.status("commander", "working", `Delegating: ${title}`, "user");
        const boss = sim.state.agents.commander.name;
        for (const d of delegates) {
          const r = sim.requestTask(d, { title: `${PART[d] ?? "Help"} — ${title}`, description: task.summary, category: ROLE_CATEGORY[d] }, { by: "commander", parent: taskId });
          if (!r.ok) continue;
          kids.push(r.taskId);
          sim.say(d, "info", `${boss} asked me to help with “${title}”. ${r.queuedBehind ? "It's queued after my current task." : "Starting my part now."} (demo)`, r.taskId);
        }
        sim.status("commander", "working", `Coordinating: ${title}`, "user");
      }),
      until((sim) => kids.every((id) => ["completed", "cancelled"].includes(sim.state.tasks[id].status)), 300),
      run((sim) => {
        sim.emit({ type: "task.phase", taskId, phase: "reporting" });
        sim.status("commander", "reporting", "Summarizing the team result", "user");
      }),
      wait(2.5),
      run((sim) => {
        const names = kids.filter((id) => sim.state.tasks[id].status === "completed").map((id) => sim.state.agents[sim.state.tasks[id].agent!].name);
        sim.finishUserTask("commander", taskId, resultMessage("team", title, names));
      }),
    ];
  }

  /** Completes a user task, reports the simulated result in the chat, then starts the next one or resumes the demo work. */
  private finishUserTask(agent: AgentId, taskId: string, result: string) {
    const task = this.state.tasks[taskId];
    for (const id of task.subtasks) if (this.state.subtasks[id].status !== "completed") this.emit({ type: "subtask.completed", subtaskId: id, agent });
    this.emit({ type: "task.completed", taskId });
    this.say(agent, "result", result, taskId);
    // this script ends here: drop its runner now so the next task's can start in the same step
    this.runners = this.runners.filter((r) => r.name !== `user:${agent}`);
    if ((this.state.queues[agent] ?? []).length) {
      this.emit({ type: "task.finished", taskId, agent, chain: true });
      this.status(agent, "completed", `Done: ${task.title}`, "user");
      this.startNextUserTask(agent);
      return;
    }
    this.resumeDemoWork(agent, taskId, `Done: ${task.title}`);
  }

  /** Back to the demo work set aside, or to what the demo asked for meanwhile (read before it is cleared). */
  private resumeDemoWork(agent: AgentId, taskId: string, doneLabel?: string) {
    const a = this.state.agents[agent];
    const goal = a.deferred?.goal ?? a.resume?.goal ?? a.goal;
    const status = a.deferred?.status ?? a.resume?.status ?? "idle";
    const detail = a.deferred?.status ? a.deferred.detail : a.resume?.detail;
    this.emit({ type: "task.finished", taskId, agent, chain: false });
    this.goal(agent, goal.anchor, goal.activity);
    this.status(agent, status, detail);
    if (doneLabel) this.status(agent, "completed", doneLabel);
  }

  /** An agent line in its chat. */
  say(agent: AgentId, kind: ChatKind, text: string, taskId?: string, proposal?: TaskProposal) {
    this.emit({ type: "chat.message", agent, messageId: `M${++this.messageSeq}`, from: "agent", text, kind, taskId, proposal });
  }

  conversation(agent: AgentId): readonly ChatMessage[] {
    return this.state.conversations[agent] ?? [];
  }

  /** Opens an agent's chat: the first time, it greets the user (a predefined line for its role). */
  openChat(agent: AgentId) {
    if (!this.has(agent) || this.conversation(agent).length) return;
    this.say(agent, "greeting", GREETINGS[agent]);
  }

  /** The user writes to an agent; it answers from local templates (a reply, or a task it proposes). */
  sendMessage(agent: AgentId, raw: string): MessageCheck {
    const check = checkMessage(raw);
    if (!check.ok || !this.has(agent)) return check;
    this.emit({ type: "chat.message", agent, messageId: `M${++this.messageSeq}`, from: "user", text: check.text, kind: "user" });
    const a = this.state.agents[agent];
    const answer = interpret(check.text, {
      agent, name: a.name, doing: a.detail || STATUS[a.status].label,
      activeTask: a.userTaskId ? this.state.tasks[a.userTaskId].title : null, queued: (this.state.queues[agent] ?? []).length,
    });
    if (answer.kind === "proposal") this.say(agent, "reply", answer.text, undefined, answer.proposal);
    else this.say(agent, "reply", answer.text);
    return check;
  }

  /**
   * The user answers a task the agent proposed: assign it (queued behind current work), switch to it now
   * (the current user task is set aside on purpose), or decline. A proposal is answered only once.
   */
  answerProposal(agent: AgentId, messageId: string, action: "assign" | "replace" | "dismiss"): boolean {
    const m = this.conversation(agent).find((x) => x.id === messageId);
    if (!m?.proposal || m.proposal.status !== "open") return false;
    if (action === "dismiss") {
      this.emit({ type: "chat.proposal", agent, messageId, resolution: "dismissed" });
      this.say(agent, "reply", "No problem. Just ask when you need something.");
      return true;
    }
    const replacing = action === "replace" && this.busyWithUser(agent);
    if (replacing) {
      const cur = this.state.agents[agent].userTaskId!;
      this.cancelActive(agent, "replaced by a new request");
      this.say(agent, "info", `Setting “${this.state.tasks[cur].title}” aside.`, cur);
    }
    const r = this.requestTask(agent, m.proposal, { front: replacing });
    if (!r.ok) {
      this.emit({ type: "chat.proposal", agent, messageId, resolution: "dismissed" });
      this.say(agent, "reply", rejection(r.reason, m.proposal.title));
      const a = this.state.agents[agent];
      if (!a.userTaskId && (a.resume || a.deferred)) this.resumeDemoWork(agent, "");
      return false;
    }
    this.emit({ type: "chat.proposal", agent, messageId, resolution: replacing ? "replaced" : r.queuedBehind ? "queued" : "assigned" });
    this.say(agent, "ack", ackMessage(m.proposal.title, r.queuedBehind), r.taskId);
    return true;
  }

  /** A quick-task chip: the user's request and the assignment in one go. */
  quickTask(agent: AgentId, quickId: string): AssignResult | null {
    const q = QUICK_TASKS[agent]?.find((x) => x.id === quickId);
    if (!q || !this.has(agent)) return null;
    this.emit({ type: "chat.message", agent, messageId: `M${++this.messageSeq}`, from: "user", text: q.label, kind: "user" });
    const r = this.requestTask(agent, { title: q.title, description: q.label, category: q.category });
    this.say(agent, r.ok ? "ack" : "reply", r.ok ? ackMessage(q.title, r.queuedBehind) : rejection(r.reason, q.title), r.ok ? r.taskId : undefined);
    return r;
  }

  /** The agent's user-assigned tasks, newest first (the MockAgentTask view). */
  userTasks(agent: AgentId): MockAgentTask[] {
    return this.state.taskOrder
      .map((id) => this.state.tasks[id])
      .filter((t) => t.source === "user" && t.agent === agent)
      .reverse()
      .map((t) => ({
        id: t.id, agentId: agent, title: t.title, description: t.summary, category: t.category!, status: t.phase!, progress: this.taskProgress(t.id),
        createdAt: t.createdAt, by: t.by ?? "user",
      }));
  }

  // ------------------------------------------------------------- UI triggers
  triggerBlocked() {
    this.startIncident();
  }

  /** Completes every active subtask (the main script then moves on to the report). */
  triggerComplete() {
    for (const st of Object.values(this.state.subtasks)) {
      if (st.status === "active" && st.taskId === this.state.currentTaskId && !st.id.endsWith(":report")) {
        this.emit({ type: "task.progress", subtaskId: st.id, progress: 1 });
      }
    }
  }

  triggerReport() {
    if (!this.reportRunning && !this.reportDone) this.startReport();
  }

  // ------------------------------------------------------------- read-outs
  /** Active agents: not idle, sleeping or resting. */
  activeCount(): number {
    return this.agentIds.filter((id) => !["idle", "sleeping", "resting"].includes(this.state.agents[id].status)).length;
  }

  inProgressCount(): number {
    return Object.values(this.state.tasks).filter((t) => t.status !== "completed" && t.status !== "cancelled").length;
  }

  phase(): string {
    const s = this.state;
    const task = s.currentTaskId ? s.tasks[s.currentTaskId] : null;
    if (!task) return "Waiting for a task";
    if (task.status === "completed") return "Task completed";
    if (task.status === "blocked") return "Blocked — Ops is investigating";
    if (this.reportRunning) return "Reporting";
    return "Working";
  }
}

function rejection(reason: "duplicate" | "queue_full" | "unknown_agent", title: string): string {
  if (reason === "duplicate") return `“${title}” is already on my list.`;
  if (reason === "queue_full") return `My queue is full (${MAX_QUEUE} tasks waiting). Let me finish one first.`;
  return "I can't take tasks right now.";
}
