import { describe, expect, it } from "vitest";
import { resolveApiOrigin } from "./origin.cjs";

describe("Electron API origin", () => {
  it("uses the configured backend port by default", () => {
    expect(resolveApiOrigin({ OPENBOT_BACKEND_PORT: "8123" })).toBe("http://127.0.0.1:8123");
    expect(resolveApiOrigin({})).toBe("http://127.0.0.1:8000");
  });

  it("prefers explicit API and remote deployment URLs", () => {
    expect(resolveApiOrigin({ OPENBOT_API_URL: "http://api.example.test:9000" })).toBe("http://api.example.test:9000");
    expect(resolveApiOrigin({ OPENBOT_URL: "https://openbot.example.test/workspace" })).toBe("https://openbot.example.test");
  });
});
