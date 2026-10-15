import type { AppSetting } from "../api/types";

export interface SettingGroup { name: string; items: AppSetting[] }

/** Group in the order the server lists them (Run limits, Context, Memory, Model routing). */
export function groupSettings(rows: AppSetting[]): SettingGroup[] {
  const groups: SettingGroup[] = [];
  for (const row of rows) {
    const g = groups.find((x) => x.name === row.group) ?? (groups.push({ name: row.group, items: [] }), groups[groups.length - 1]);
    g.items.push(row);
  }
  return groups;
}

export type Parsed = { value: unknown } | { error: string };

/** Form text to the typed value the API expects; the server re-validates types and ranges. */
export function parseSettingInput(type: AppSetting["type"], raw: string): Parsed {
  const text = raw.trim();
  switch (type) {
    case "int":
      return /^-?\d+$/.test(text) ? { value: Number(text) } : { error: "must be a whole number" };
    case "float": {
      const n = Number(text);
      return text !== "" && Number.isFinite(n) ? { value: n } : { error: "must be a number" };
    }
    case "list":
      return { value: text ? text.split(",").map((p) => p.trim()).filter(Boolean) : [] };
    case "bool":
      return { value: text === "true" };
    default:
      return { value: text };
  }
}

export function formatSettingValue(type: AppSetting["type"], value: unknown): string {
  if (value == null) return "";
  if (type === "list" && Array.isArray(value)) return value.join(", ");
  return String(value);
}
