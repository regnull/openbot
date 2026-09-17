import type { McpServer } from "../api/types";

export type McpTone = "zinc" | "green" | "amber" | "red" | "blue";
export type McpAction = "connect" | "reconnect" | "disconnect" | "forget" | "remove";

const NAME_RE = /^[a-zA-Z0-9_-]{1,40}$/;

/** Client-side check for the Add server dialog; the server re-validates. */
export function validateNewMcpServer(name: string, url: string): { name?: string; url?: string } {
  const errors: { name?: string; url?: string } = {};
  const n = name.trim();
  if (!n) errors.name = "Name is required";
  else if (!NAME_RE.test(n)) errors.name = "Letters, digits, _ and - only (up to 40)";
  const u = url.trim();
  let parsed: URL | null = null;
  try { parsed = new URL(u); } catch { parsed = null; }
  if (!parsed || !parsed.host) errors.url = "Enter an absolute URL, for example https://mcp.example.com/mcp";
  else {
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
    if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && local)) errors.url = "Use https (http is allowed for localhost only)";
  }
  return errors;
}

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
  const base = ((): McpAction[] => {
    switch (s.status) {
      case "disabled": return [];
      case "connecting": return [];
      case "authorizing": return ["disconnect"];
      case "connected": return s.oauth ? ["reconnect", "disconnect", "forget"] : ["reconnect", "disconnect"];
      case "needs_auth": return ["connect"];
      case "disconnected": return s.oauth ? ["connect", "forget"] : ["connect"];
      default: return ["connect"];
    }
  })();
  // Servers added from Settings can be removed there; file servers are edited in mcp.json.
  return s.source === "db" && s.status !== "connecting" ? [...base, "remove"] : base;
}

/** True while a status is transient, which drives polling of the server list. */
export const mcpInFlight = (servers: McpServer[]): boolean => servers.some((s) => s.status === "connecting" || s.status === "authorizing");
