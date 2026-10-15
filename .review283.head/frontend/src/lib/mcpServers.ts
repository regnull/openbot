import type { McpServer } from "../api/types";

export type McpTone = "zinc" | "green" | "amber" | "red" | "blue";
export type McpAction = "connect" | "reconnect" | "disconnect" | "forget" | "remove";

const NAME_RE = /^[a-zA-Z0-9_-]{1,40}$/;

export type McpTransport = "http" | "stdio";
export interface ServerFormErrors { name?: string; url?: string; command?: string }

/** Client-side check for the Add/Edit server dialog; the server re-validates. */
export function validateNewMcpServer(name: string, url: string, transport: McpTransport = "http", command = ""): ServerFormErrors {
  const errors: ServerFormErrors = {};
  const n = name.trim();
  if (!n) errors.name = "Name is required";
  else if (!NAME_RE.test(n)) errors.name = "Letters, digits, _ and - only (up to 40)";
  if (transport === "stdio") {
    if (!command.trim()) errors.command = "Command is required";
    return errors;
  }
  const u = url.trim();
  if (u.includes("${")) return errors;                      // a variable reference; checked when connecting
  let parsed: URL | null = null;
  try { parsed = new URL(u); } catch { parsed = null; }
  if (!parsed || !parsed.host) errors.url = "Enter an absolute URL, for example https://mcp.example.com/mcp";
  else {
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
    if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && local)) errors.url = "Use https (http is allowed for localhost only)";
  }
  return errors;
}

/** `KEY=value` per line (values may contain `=`); blank lines ignored; the first bad line is reported. */
export function parseKeyValues(text: string): { values: Record<string, string>; error?: string } {
  const values: Record<string, string> = {};
  let error: string | undefined;
  text.split("\n").forEach((line, i) => {
    const raw = line.trim();
    if (!raw) return;
    const eq = raw.indexOf("=");
    if (eq <= 0) { error ??= `Line ${i + 1} is not KEY=value`; return; }
    values[raw.slice(0, eq).trim()] = raw.slice(eq + 1).trim();
  });
  return error ? { values, error } : { values };
}

export const formatKeyValues = (values: Record<string, string>): string => Object.entries(values).map(([k, v]) => `${k}=${v}`).join("\n");

/** Shell-style argument splitting: whitespace separates, "double" or 'single' quotes group. */
export function parseArgs(text: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quote: string | null = null;
  let has = false;
  for (const ch of text) {
    if (quote) {
      if (ch === quote) quote = null; else cur += ch;
    } else if (ch === '"' || ch === "'") { quote = ch; has = true; }
    else if (/\s/.test(ch)) { if (has || cur) out.push(cur); cur = ""; has = false; }
    else cur += ch;
  }
  if (has || cur) out.push(cur);
  return out;
}

/** The inverse of parseArgs: arguments that contain whitespace or quotes are double-quoted. */
export const formatArgs = (args: string[]): string =>
  args.map((a) => (/[\s"']/.test(a) || a === "" ? `"${a.replace(/"/g, '\\"')}"` : a)).join(" ");

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
