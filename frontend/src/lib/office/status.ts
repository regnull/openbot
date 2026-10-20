/**
 * Agent status model for the Living Office and the bubble each status shows.
 *
 * Idle is not Sleeping: idle shows no bubble (or subtle dots), and Zzz appears only for an
 * Openling that is explicitly sleeping. One primary bubble per Openling, chosen by priority.
 */
import type { OpenlingExpression } from "../openlings/expressions";

export type AgentStatus =
  | "idle" | "waiting" | "thinking" | "working" | "coding" | "testing" | "blocked" | "human_review"
  | "reporting" | "completed" | "resting" | "sleeping";

export type BubbleIcon = "dots" | "hourglass" | "bulb" | "code" | "checklist" | "alert" | "review" | "chart" | "check" | "rest" | "zzz";
export type BubbleTone = "calm" | "active" | "warn" | "danger" | "ok" | "rest";

export interface StatusInfo {
  id: AgentStatus;
  label: string;
  /** null: no bubble for this status. */
  icon: BubbleIcon | null;
  tone: BubbleTone;
  /** Higher wins when several statuses apply at once. */
  priority: number;
  expression: OpenlingExpression;
  /** Shown briefly, then the agent falls back to its underlying status. */
  transient?: number;
}

export const STATUS: Record<AgentStatus, StatusInfo> = {
  human_review: { id: "human_review", label: "Needs human review", icon: "review", tone: "danger", priority: 6, expression: "Worried" },
  blocked: { id: "blocked", label: "Blocked", icon: "alert", tone: "danger", priority: 5, expression: "Worried" },
  reporting: { id: "reporting", label: "Reporting", icon: "chart", tone: "active", priority: 4, expression: "Reporting" },
  completed: { id: "completed", label: "Completed", icon: "check", tone: "ok", priority: 4, expression: "Happy", transient: 4 },
  thinking: { id: "thinking", label: "Thinking", icon: "dots", tone: "active", priority: 3, expression: "Focused" },
  working: { id: "working", label: "Working", icon: "bulb", tone: "active", priority: 3, expression: "Focused" },
  coding: { id: "coding", label: "Coding", icon: "code", tone: "active", priority: 3, expression: "Focused" },
  testing: { id: "testing", label: "Testing", icon: "checklist", tone: "active", priority: 3, expression: "Focused" },
  waiting: { id: "waiting", label: "Waiting", icon: "hourglass", tone: "calm", priority: 2, expression: "Neutral" },
  resting: { id: "resting", label: "Resting", icon: "rest", tone: "rest", priority: 2, expression: "Neutral" },
  sleeping: { id: "sleeping", label: "Sleeping", icon: "zzz", tone: "rest", priority: 2, expression: "Neutral" },
  idle: { id: "idle", label: "Idle", icon: null, tone: "calm", priority: 1, expression: "Neutral" },
};

export const STATUS_IDS = Object.keys(STATUS) as AgentStatus[];

/** The status whose bubble shows, from everything that applies to an agent right now. */
export function primaryStatus(active: readonly AgentStatus[]): AgentStatus {
  let best: AgentStatus = "idle";
  for (const s of active) if (STATUS[s].priority > STATUS[best].priority) best = s;
  return best;
}

/** Bubble shown for a status (null for none). */
export function bubbleFor(status: AgentStatus): { icon: BubbleIcon; tone: BubbleTone; label: string } | null {
  const s = STATUS[status];
  return s.icon ? { icon: s.icon, tone: s.tone, label: s.label } : null;
}
