import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(path.join(__dirname, "main.cjs"), "utf8");
const builderSource = readFileSync(path.join(__dirname, "../../electron-builder.yml"), "utf8");
const backendScriptSource = readFileSync(path.join(__dirname, "../../scripts/electron-backend.sh"), "utf8");

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

  it("shows the operator why the app failed to start instead of quitting silently", () => {
    // A backend that never comes up used to just make the app quit with no window and nothing
    // visible -- indistinguishable from it not launching at all.
    expect(mainSource).toContain("dialog.showErrorBox(");
  });

  it("does not ship a bundled venv, which would carry an absolute shebang back to the build machine", () => {
    // uv's venv scripts hardcode the path of the machine that ran `uv sync`; bundling one only
    // works on the machine that built the package. Ship the source and let uv build a fresh one.
    expect(builderSource).toMatch(/!\.venv\/?$|!\.venv\/\*\*/);
  });

  it("resolves uv from more than just an inherited PATH", () => {
    // A GUI-launched app (double-clicked, not run from a terminal) gets a minimal launchd PATH
    // that excludes user-local install directories, so `command -v uv` alone is not enough.
    expect(backendScriptSource).toContain("command -v uv");
    expect(backendScriptSource).toContain('"$HOME/.local/bin/uv"');
    expect(backendScriptSource).not.toMatch(/^exec uv run/m);
  });

  it("builds the venv in the writable user-data dir, not inside the app bundle", () => {
    // The bundle's Resources dir is not reliably writable once installed and signed.
    expect(backendScriptSource).toContain('export UV_PROJECT_ENVIRONMENT="${OPENBOT_USER_DATA}/venv"');
  });
});
