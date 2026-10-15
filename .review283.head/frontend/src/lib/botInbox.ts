import type { BotInboxItem, PurgeResult } from "../api/types";

export type RowTone = "zinc" | "green" | "amber" | "red" | "blue";
export interface RowState { label: string; tone: RowTone; open: boolean }

/** What to say about an inbox item: the item's own status while it waits, the run's once one exists. */
export function inboxRowState(item: BotInboxItem): RowState {
  if (item.status === "queued") return { label: "queued", tone: "zinc", open: true };
  if (item.status === "cancelled" || item.run_status === "cancelled") return { label: "cancelled", tone: "zinc", open: false };
  if (item.run_status === "waiting_human") return { label: "waiting for you", tone: "amber", open: true };
  if (item.status === "processing" || item.run_status === "running" || item.run_status === "queued") return { label: "running", tone: "blue", open: true };
  if (item.run_status === "failed" || item.status === "failed") return { label: "failed", tone: "red", open: false };
  if (item.reply) return { label: "replied", tone: "green", open: false };
  return { label: "done, no reply", tone: "zinc", open: false };
}

/** True while anything is still in flight; the inbox view polls only then. */
export const hasOpenItems = (items: BotInboxItem[]): boolean => items.some((i) => inboxRowState(i).open);

/** One line for what a purge did, so "nothing happened" reads as such rather than as a silent no-op. */
export function purgeSummary(r: PurgeResult): string {
  if (!r.cancelled_runs && !r.purged_items) return "Nothing to cancel: no open run and an empty queue.";
  const runs = r.cancelled_runs === 1 ? "1 run" : `${r.cancelled_runs} runs`;
  const items = r.purged_items === 1 ? "1 queued item" : `${r.purged_items} queued items`;
  return `Cancelled ${runs}, dropped ${items}.`;
}
