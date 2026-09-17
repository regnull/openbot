import type { ToolInfo } from "../api/types";

export interface ServerGroup { server: string; tools: ToolInfo[] }
export interface GroupedTools { flat: ToolInfo[]; servers: ServerGroup[] }

/** Built-ins and plugins stay a flat list; MCP tools (source `mcp:<server>`) group by server. */
export function groupTools(tools: ToolInfo[]): GroupedTools {
  const flat: ToolInfo[] = [];
  const byServer = new Map<string, ToolInfo[]>();
  for (const t of tools) {
    if (t.source.startsWith("mcp:")) {
      const server = t.source.slice(4);
      byServer.set(server, [...(byServer.get(server) ?? []), t]);
    } else flat.push(t);
  }
  return { flat, servers: [...byServer.entries()].map(([server, ts]) => ({ server, tools: ts })) };
}

export type GroupState = "none" | "some" | "all";

export function groupState(names: string[], selected: string[]): GroupState {
  const n = names.filter((x) => selected.includes(x)).length;
  return n === 0 ? "none" : n === names.length ? "all" : "some";
}

interface Selection { tool_names: string[]; approval_tools: string[] }

/** Group checkbox: select every tool of the server unless all already are, in which case clear them.
 *  Approvals for cleared tools are dropped, since approval_tools must stay a subset of tool_names. */
export function toggleGroup(sel: Selection, names: string[]): Selection {
  if (groupState(names, sel.tool_names) === "all") {
    return { tool_names: sel.tool_names.filter((n) => !names.includes(n)), approval_tools: sel.approval_tools.filter((n) => !names.includes(n)) };
  }
  return { tool_names: [...sel.tool_names, ...names.filter((n) => !sel.tool_names.includes(n))], approval_tools: sel.approval_tools };
}
