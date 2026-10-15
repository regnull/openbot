import { describe, expect, it } from "vitest";
import type { AppSetting } from "../api/types";
import { formatSettingValue, groupSettings, parseSettingInput } from "./appSettings";

const s = (key: string, group: string, type: AppSetting["type"], value: unknown, def: unknown = value): AppSetting =>
  ({ key, group, label: key, description: "", type, value, default: def, overridden: value !== def, secret: false, is_set: true });

describe("groupSettings", () => {
  it("keeps the server's group order and puts each setting under its group", () => {
    const rows = [s("a", "Run limits", "int", 1), s("b", "Context", "int", 2), s("c", "Run limits", "int", 3), s("d", "Memory", "float", 4)];
    expect(groupSettings(rows).map((g) => [g.name, g.items.map((i) => i.key)])).toEqual([
      ["Run limits", ["a", "c"]], ["Context", ["b"]], ["Memory", ["d"]],
    ]);
  });
});

describe("parseSettingInput", () => {
  it("turns form text into the typed value the API expects", () => {
    expect(parseSettingInput("int", " 60 ")).toEqual({ value: 60 });
    expect(parseSettingInput("float", "1.5")).toEqual({ value: 1.5 });
    expect(parseSettingInput("list", "z-ai, fireworks")).toEqual({ value: ["z-ai", "fireworks"] });
    expect(parseSettingInput("list", "")).toEqual({ value: [] });
    expect(parseSettingInput("str", "openai/gpt-5.5")).toEqual({ value: "openai/gpt-5.5" });
  });
  it("rejects text that is not a number for numeric settings", () => {
    expect(parseSettingInput("int", "many")).toEqual({ error: "must be a whole number" });
    expect(parseSettingInput("int", "1.5")).toEqual({ error: "must be a whole number" });
    expect(parseSettingInput("float", "x")).toEqual({ error: "must be a number" });
  });
});

describe("formatSettingValue", () => {
  it("renders lists as comma-separated text and nulls as empty", () => {
    expect(formatSettingValue("list", ["z-ai", "fireworks"])).toBe("z-ai, fireworks");
    expect(formatSettingValue("str", null)).toBe("");
    expect(formatSettingValue("int", 60)).toBe("60");
  });
});

describe("secret settings", () => {
  it("parses a secret as text and formats a masked value as the mask", () => {
    expect(parseSettingInput("secret", " sk-1 ")).toEqual({ value: "sk-1" });
    expect(parseSettingInput("secret", "")).toEqual({ value: "" });
    expect(formatSettingValue("secret", "••••••••")).toBe("••••••••");
    expect(formatSettingValue("secret", null)).toBe("");
  });
});
