import { describe, expect, it } from "vitest";
import { BOT_ICONS, DEFAULT_BOT_ICON, botIconFor } from "./botIcons";

describe("bot icons", () => {
  it("has a default standard icon", () => {
    expect(DEFAULT_BOT_ICON).toBe("robot");
    expect(BOT_ICONS.map((icon) => icon.key)).toContain(DEFAULT_BOT_ICON);
  });

  it("returns the matching icon or falls back to default", () => {
    expect(botIconFor("code").glyph).toBe("💻");
    expect(botIconFor("missing").key).toBe(DEFAULT_BOT_ICON);
    expect(botIconFor(null).key).toBe(DEFAULT_BOT_ICON);
  });
});
