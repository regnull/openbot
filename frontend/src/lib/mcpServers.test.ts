import { describe, expect, it } from "vitest";
import type { McpServer } from "../api/types";
import { mcpActions, mcpStatusBadge, validateNewMcpServer } from "./mcpServers";

const server = (status: McpServer["status"], oauth = false): McpServer =>
  ({ name: "linear", transport: "http", status, enabled: status !== "disabled", oauth, url: "https://x/mcp", error: null, tools: [], source: "file", authorization_url: null });

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

describe("validateNewMcpServer", () => {
  it("accepts a name and an https URL, http only for localhost", () => {
    expect(validateNewMcpServer("linear", "https://mcp.linear.app/mcp")).toEqual({});
    expect(validateNewMcpServer("local", "http://localhost:8002/mcp")).toEqual({});
    expect(validateNewMcpServer("", "https://x/mcp")).toEqual({ name: "Name is required" });
    expect(validateNewMcpServer("bad name!", "https://x/mcp")).toEqual({ name: "Letters, digits, _ and - only (up to 40)" });
    expect(validateNewMcpServer("ok", "mcp.example.com")).toEqual({ url: "Enter an absolute URL, for example https://mcp.example.com/mcp" });
    expect(validateNewMcpServer("ok", "http://mcp.example.com/mcp")).toEqual({ url: "Use https (http is allowed for localhost only)" });
  });
});

describe("mcpActions for servers added from Settings", () => {
  it("adds remove for database servers only", () => {
    const db = { ...server("connected"), source: "db" as const };
    expect(mcpActions(db)).toEqual(["reconnect", "disconnect", "remove"]);
    expect(mcpActions({ ...server("needs_auth", true), source: "db" })).toEqual(["connect", "remove"]);
    expect(mcpActions({ ...server("connected"), source: "file" })).toEqual(["reconnect", "disconnect"]);
  });
});
