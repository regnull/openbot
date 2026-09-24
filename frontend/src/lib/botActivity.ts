import type { Bot, BusEvent } from "../api/types";

export const botActivityQueryKeys = [["bots"], ["bot"]] as const;

export function activeBotIds(bots: Bot[] | undefined): Set<string> {
  return new Set((bots ?? []).filter((bot) => bot.active).map((bot) => bot.id));
}

export function botActivityLabel(active: boolean): string {
  return active ? "active" : "idle";
}

export function shouldRefreshBots(e: BusEvent): boolean {
  if (e.event === "bots.updated") return true;
  if (e.event !== "run.updated") return false;
  const status = typeof e.data?.status === "string" ? e.data.status : "";
  return ["queued", "running", "waiting_human", "completed", "failed", "cancelled"].includes(status);
}
