import { describe, expect, it } from "vitest";
import type { McpServer } from "../api/types";
import { mcpActions, mcpStatusBadge } from "./mcpServers";

const server = (status: McpServer["status"], oauth = false): McpServer =>
  ({ name: "linear", transport: "http", status, enabled: status !== "disabled", oauth, url: "https://x/mcp", error: null, tools: [] });

describe("mcpStatusBadge", () => {
  it("maps each server status to a label and tone", () => {
    expect(mcpStatusBadge(server("connected"))).toEqual({ label: "connected", tone: "green" });
    expect(mcpStatusBadge(server("needs_auth"))).toEqual({ label: "needs authorization", tone: "amber" });
    expect(mcpStatusBadge(server("authorizing"))).toEqual({ label: "waiting for authorization", tone: "amber" });
    expect(mcpStatusBadge(server("connecting"))).toEqual({ label: "connecting", tone: "blue" });
    expect(mcpStatusBadge(server("error"))).toEqual({ label: "error", tone: "red" });
    expect(mcpStatusBadge(server("disconnected"))).toEqual({ label: "disconnected", tone: "zinc" });
    expect(mcpStatusBadge(server("disabled"))).toEqual({ label: "disabled", tone: "zinc" });
  });
});

describe("mcpActions", () => {
  it("offers the right buttons for each state", () => {
    expect(mcpActions(server("connected"))).toEqual(["reconnect", "disconnect"]);
    expect(mcpActions(server("connected", true))).toEqual(["reconnect", "disconnect", "forget"]);
    expect(mcpActions(server("needs_auth", true))).toEqual(["connect"]);
    expect(mcpActions(server("disconnected", true))).toEqual(["connect", "forget"]);
    expect(mcpActions(server("error"))).toEqual(["connect"]);
    expect(mcpActions(server("authorizing", true))).toEqual(["disconnect"]);
    expect(mcpActions(server("disabled"))).toEqual([]);
  });
});
