import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(path.join(__dirname, "main.cjs"), "utf8");
const builderSource = readFileSync(path.join(__dirname, "../../electron-builder.yml"), "utf8");

describe("Electron packaged startup", () => {
  it("uses the branded macOS bundle and ships backend resources", () => {
    expect(builderSource).toContain("productName: OpenBot");
    expect(builderSource).toContain("target:");
    expect(builderSource).toContain("- dmg");
    expect(builderSource).toContain("- zip");
    expect(builderSource).toContain("to: backend");
  });

  it("waits for backend health and terminates its process group", () => {
    expect(mainSource).toContain("/api/v1/health");
    expect(mainSource).toContain("process.kill(-backendProcess.pid, \"SIGTERM\")");
    expect(mainSource).toContain("await waitForBackend();");
  });

  it("skips bundled backend startup and readiness for explicit API or remote URLs", () => {
    expect(mainSource).toContain("const usesExternalBackend = Boolean(process.env.OPENBOT_URL || process.env.OPENBOT_API_URL);");
    expect(mainSource).toContain("if (isDevelopment || usesExternalBackend) return;");
    expect(mainSource).toContain("if (isDevelopment || usesExternalBackend) return;\n  const healthUrl");
  });

  it("quits on window-all-closed in development, including macOS", () => {
    expect(mainSource).toMatch(/app\.on\("window-all-closed",\s*\(\)\s*=>\s*\{\s*if \(process\.platform !== "darwin" \|\| isDevelopment\) app\.quit\(\);/);
  });
});
