import { describe, expect, it } from "vitest";
import { parseBackendUrl, resolveApiOrigin } from "./origin.cjs";

describe("parseBackendUrl", () => {
  it("returns null when no flag is present", () => {
    expect(parseBackendUrl(["node", "main.cjs"])).toBeNull();
  });

  it("parses --backend_url with space separator", () => {
    expect(parseBackendUrl(["node", "main.cjs", "--backend_url", "http://remote:9000"])).toBe("http://remote:9000");
  });

  it("parses --backend_url=value form", () => {
    expect(parseBackendUrl(["node", "main.cjs", "--backend_url=http://remote:9000"])).toBe("http://remote:9000");
  });

  it("strips trailing slashes", () => {
    expect(parseBackendUrl(["node", "main.cjs", "--backend_url", "http://remote:9000/"])).toBe("http://remote:9000");
    expect(parseBackendUrl(["node", "main.cjs", "--backend_url=http://remote:9000///"])).toBe("http://remote:9000");
  });

  it("returns null when --backend_url has no value", () => {
    expect(parseBackendUrl(["node", "main.cjs", "--backend_url"])).toBeNull();
  });

  it("handles --backend_url after other flags", () => {
    expect(parseBackendUrl(["node", "main.cjs", "--no-sandbox", "--backend_url", "http://x:1"])).toBe("http://x:1");
  });
});

describe("Electron API origin", () => {
  it("uses the configured backend port by default", () => {
    expect(resolveApiOrigin({ OPENBOT_BACKEND_PORT: "8123" }, null)).toBe("http://127.0.0.1:8123");
    expect(resolveApiOrigin({}, null)).toBe("http://127.0.0.1:8000");
  });

  it("prefers explicit API and remote deployment URLs", () => {
    expect(resolveApiOrigin({ OPENBOT_API_URL: "http://api.example.test:9000" }, null)).toBe("http://api.example.test:9000");
    expect(resolveApiOrigin({ OPENBOT_URL: "https://openbot.example.test/workspace" }, null)).toBe("https://openbot.example.test");
  });

  it("takes priority over env-based URLs when --backend_url is provided", () => {
    expect(resolveApiOrigin({ OPENBOT_API_URL: "http://env.example.test:9000" }, "http://cli.example.test:7000")).toBe("http://cli.example.test:7000");
  });
});
