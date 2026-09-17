import type { McpServer } from "../api/types";

export type McpTone = "zinc" | "green" | "amber" | "red" | "blue";
export type McpAction = "connect" | "reconnect" | "disconnect" | "forget";

export function mcpStatusBadge(s: McpServer): { label: string; tone: McpTone } {
  switch (s.status) {
    case "connected": return { label: "connected", tone: "green" };
    case "needs_auth": return { label: "needs authorization", tone: "amber" };
    case "authorizing": return { label: "waiting for authorization", tone: "amber" };
    case "connecting": return { label: "connecting", tone: "blue" };
    case "error": return { label: "error", tone: "red" };
    case "disabled": return { label: "disabled", tone: "zinc" };
    default: return { label: "disconnected", tone: "zinc" };
  }
}

/** Which buttons a server row shows. "forget" drops stored OAuth credentials and only applies to OAuth servers. */
export function mcpActions(s: McpServer): McpAction[] {
  switch (s.status) {
    case "disabled": return [];
    case "connecting": return [];
    case "authorizing": return ["disconnect"];
    case "connected": return s.oauth ? ["reconnect", "disconnect", "forget"] : ["reconnect", "disconnect"];
    case "needs_auth": return ["connect"];
    case "disconnected": return s.oauth ? ["connect", "forget"] : ["connect"];
    default: return ["connect"];
  }
}

/** True while a status is transient, which drives polling of the server list. */
export const mcpInFlight = (servers: McpServer[]): boolean => servers.some((s) => s.status === "connecting" || s.status === "authorizing");
