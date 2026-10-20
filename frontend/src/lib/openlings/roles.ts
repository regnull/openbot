import type { OpenlingClip } from "./animations";
import type { OpenlingExpression } from "./expressions";
import type { PlacedMode, PropId } from "./props";

/**
 * The six AI-agent roles. Every role is the same Base Openling (mesh, jacket, rig and
 * clips); a role only chooses props, a body clip, an expression and a name.
 */
export type RoleId = "commander" | "coder" | "researcher" | "tester" | "ops" | "reporter";

export interface RolePreset {
  id: RoleId;
  label: string;
  summary: string;
  clip: OpenlingClip;
  expression: OpenlingExpression;
  props: readonly { id: PropId; placement: PlacedMode }[];
}

export const ROLES: readonly RolePreset[] = [
  {
    id: "commander", label: "Commander", summary: "Leads the team, keeps everyone aligned",
    clip: "Reporting", expression: "Neutral",
    props: [{ id: "bluetooth_earpiece", placement: "worn" }, { id: "tablet", placement: "heldLeft" }],
  },
  {
    id: "coder", label: "Coder", summary: "Builds, improves, turns ideas into reality",
    clip: "Typing", expression: "Focused",
    props: [{ id: "square_glasses", placement: "worn" }, { id: "laptop", placement: "desk" }],
  },
  {
    id: "researcher", label: "Researcher", summary: "Explores, learns, finds what's next",
    clip: "Reporting", expression: "Focused",
    props: [{ id: "research_goggles", placement: "worn" }, { id: "tablet", placement: "heldLeft" }],
  },
  {
    id: "tester", label: "Tester", summary: "Checks, probes, keeps things solid",
    clip: "Idle", expression: "Focused",
    props: [{ id: "cap", placement: "worn" }, { id: "paper_notebook", placement: "heldLeft" }, { id: "pen", placement: "heldRight" }],
  },
  {
    id: "ops", label: "Ops", summary: "Runs, fixes, keeps OpenBot healthy",
    clip: "Idle", expression: "Neutral",
    props: [{ id: "large_headphones", placement: "worn" }, { id: "wrench", placement: "heldRight" }, { id: "toolbox", placement: "heldLeft" }],
  },
  {
    id: "reporter", label: "Reporter", summary: "Summarizes, shares, turns progress into impact",
    clip: "Reporting", expression: "Reporting",
    props: [{ id: "round_glasses", placement: "worn" }, { id: "tablet", placement: "heldLeft" }],
  },
];

export function rolePreset(id: RoleId): RolePreset {
  const role = ROLES.find((r) => r.id === id);
  if (!role) throw new Error(`Unknown Openling role: ${id}`);
  return role;
}
