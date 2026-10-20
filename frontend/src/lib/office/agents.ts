/**
 * The Living Office cast: six role Openlings plus two background workers. Every agent is
 * the same Base Openling; a profile only picks a role preset's props, a name and where the
 * agent starts. All of it is demo data (Phase 1 does not talk to the OpenBot backend).
 */
import type { PlacedMode, PropId } from "../openlings/props";
import type { RoleId } from "../openlings/roles";

export type AgentId = "commander" | "coder" | "researcher" | "tester" | "ops" | "reporter" | "worker1" | "worker2";

/** What an Openling does once it reaches its goal anchor. */
export type Activity =
  | "idle" | "commanding" | "typing" | "seated" | "reading" | "testing" | "inspecting" | "presenting" | "reporting" | "resting"
  | "sleeping" | "coffee" | "waiting";

export interface AgentGoal {
  anchor: string;
  activity: Activity;
}

export interface AgentProfile {
  id: AgentId;
  name: string;
  roleLabel: string;
  /** Role preset whose props this agent carries (ROLES in lib/openlings/roles.ts). */
  preset: RoleId;
  /** Optional prop override for the background workers. */
  props?: readonly { id: PropId; placement: PlacedMode }[];
  start: AgentGoal;
  /** Blink / idle phase seed so no two Openlings move in lockstep. */
  seed: number;
  optional?: boolean;
}

export const AGENTS: readonly AgentProfile[] = [
  { id: "commander", name: "Atlas", roleLabel: "Commander", preset: "commander", start: { anchor: "Command_Work", activity: "commanding" }, seed: 11 },
  { id: "coder", name: "Byte", roleLabel: "Coder", preset: "coder", start: { anchor: "Break_Coffee", activity: "coffee" }, seed: 23 },
  { id: "researcher", name: "Nova", roleLabel: "Researcher", preset: "researcher", start: { anchor: "Command_VisitorWait", activity: "waiting" }, seed: 37 },
  { id: "tester", name: "Pip", roleLabel: "Tester", preset: "tester", start: { anchor: "Test_Inspect", activity: "idle" }, seed: 41 },
  { id: "ops", name: "Bolt", roleLabel: "Ops", preset: "ops", start: { anchor: "Ops_Desk", activity: "idle" }, seed: 53 },
  { id: "reporter", name: "Echo", roleLabel: "Reporter", preset: "reporter", start: { anchor: "Reporting_Seat_01", activity: "seated" }, seed: 67 },
  {
    id: "worker1", name: "Kit", roleLabel: "Worker", preset: "coder", start: { anchor: "Desk_01_Seat", activity: "typing" }, seed: 79, optional: true,
    props: [{ id: "round_glasses", placement: "worn" }, { id: "laptop", placement: "desk" }],
  },
  {
    id: "worker2", name: "Mo", roleLabel: "Worker", preset: "coder", start: { anchor: "Desk_03_Seat", activity: "typing" }, seed: 83, optional: true,
    props: [{ id: "large_headphones", placement: "worn" }, { id: "laptop", placement: "desk" }],
  },
];

export const AGENT_IDS = AGENTS.map((a) => a.id);

export function agentProfile(id: AgentId): AgentProfile {
  return AGENTS.find((a) => a.id === id)!;
}

/** Activities performed seated (the Openling backs onto or rolls up to a seat). */
export function isSeatedActivity(a: Activity): boolean {
  return a === "typing" || a === "seated" || a === "resting" || a === "sleeping";
}
