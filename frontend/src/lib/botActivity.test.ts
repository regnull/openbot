import { describe, expect, it } from "vitest";
import type { Bot } from "../api/types";
import { activeBotIds, botActivityLabel, botActivityQueryKeys, shouldRefreshBots } from "./botActivity";

const bot = (id: string, active: boolean): Bot => ({
  id,
  handle: id,
  name: id,
  description: "",
  icon: "robot",
  enabled: true,
  active,
  instructions: "",
  provider: "openai",
  model: "gpt",
  model_settings: {},
  tool_names: [],
  approval_tools: [],
  memory_enabled: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

describe("bot activity helpers", () => {
  it("finds active bots for sidebar indicators", () => {
    expect([...activeBotIds([bot("engineer", true), bot("qa", false)])]).toEqual(["engineer"]);
  });

  it("labels active and idle bots", () => {
    expect(botActivityLabel(true)).toBe("active");
    expect(botActivityLabel(false)).toBe("idle");
  });

  it("refreshes bot list when run or bot events can affect activity", () => {
    expect(shouldRefreshBots({ event: "bots.updated", thread_id: null, data: {} })).toBe(true);
    expect(shouldRefreshBots({ event: "run.updated", thread_id: "t", data: { status: "running" } })).toBe(true);
    expect(shouldRefreshBots({ event: "message.created", thread_id: "t", data: {} })).toBe(false);
  });

  it("refreshes bot list and bot detail queries", () => {
    expect(botActivityQueryKeys).toEqual([["bots"], ["bot"]]);
  });
});
