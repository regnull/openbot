import { describe, expect, it } from "vitest";
import type { ToolInfo } from "../api/types";
import { groupState, groupTools, toggleGroup, toolLabel, unavailableGrants } from "./toolGroups";

const tool = (name: string, source: string): ToolInfo => ({ name, description: name, source, args_schema: {} });
const tools = [
  tool("run_shell", "builtin"), tool("read_file", "builtin"), tool("get_time", "tools/example_tools.py"),
  tool("Linear__create_issue", "mcp:Linear"), tool("Linear__list_issues", "mcp:Linear"), tool("gh__search", "mcp:gh"),
];

describe("groupTools", () => {
  it("keeps built-ins and plugins flat and groups MCP tools by server", () => {
    const g = groupTools(tools);
    expect(g.flat.map((t) => t.name)).toEqual(["run_shell", "read_file", "get_time"]);
    expect(g.servers.map((s) => [s.server, s.tools.map((t) => t.name)])).toEqual([
      ["Linear", ["Linear__create_issue", "Linear__list_issues"]], ["gh", ["gh__search"]],
    ]);
  });
});

describe("groupState", () => {
  it("reports none, some or all of a server's tools selected", () => {
    const names = ["Linear__create_issue", "Linear__list_issues"];
    expect(groupState(names, [])).toBe("none");
    expect(groupState(names, ["Linear__create_issue"])).toBe("some");
    expect(groupState(names, ["Linear__list_issues", "Linear__create_issue", "run_shell"])).toBe("all");
  });
});

describe("toggleGroup", () => {
  it("selects every tool of the server unless all are selected, then clears them, keeping approvals consistent", () => {
    const names = ["Linear__create_issue", "Linear__list_issues"];
    expect(toggleGroup({ tool_names: ["run_shell"], approval_tools: [] }, names)).toEqual({ tool_names: ["run_shell", ...names], approval_tools: [] });
    expect(toggleGroup({ tool_names: ["run_shell", "Linear__create_issue"], approval_tools: ["Linear__create_issue"] }, names))
      .toEqual({ tool_names: ["run_shell", "Linear__create_issue", "Linear__list_issues"], approval_tools: ["Linear__create_issue"] });
    expect(toggleGroup({ tool_names: ["run_shell", ...names], approval_tools: ["Linear__create_issue", "run_shell"] }, names))
      .toEqual({ tool_names: ["run_shell"], approval_tools: ["run_shell"] });
  });
});

describe("unavailableGrants and toolLabel", () => {
  it("lists granted names the registry no longer has, and labels tools relative to their server", () => {
    expect(unavailableGrants(["run_shell", "gh__search", "Linear__list_issues"], tools)).toEqual([]);
    expect(unavailableGrants(["run_shell", "old__thing", "gh__gone"], tools)).toEqual(["old__thing", "gh__gone"]);
    expect(toolLabel("my__server", "my__server__do_it")).toBe("do_it");
    expect(toolLabel("gh", "gh__search")).toBe("search");
  });
});
