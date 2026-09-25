import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(path.join(__dirname, "main.cjs"), "utf8");
const builderSource = readFileSync(path.join(__dirname, "../../electron-builder.yml"), "utf8");
const backendScriptSource = readFileSync(path.join(__dirname, "../../scripts/electron-backend.sh"), "utf8");
const devScriptPath = path.join(__dirname, "../../scripts/electron-dev.sh");
const devScriptSource = readFileSync(devScriptPath, "utf8");

describe("Electron launcher detail controls", () => {
  it("defaults development Electron to omit details and forwards the opt-in", () => {
    expect(devScriptSource).toContain('DETAILS_FLAG="--exclude-llm-call-details"');
    expect(devScriptSource).toContain('[[ "${1:-}" == "--include-llm-call-details" ]]');
    expect(devScriptSource).toContain('shift');
    expect(devScriptSource).toContain('python -m openbot.cli "$DETAILS_FLAG"');
  });

  it("forwards the documented opt-in through make", () => {
    const output = execFileSync("make", ["-n", "electron", "--", "--include-llm-call-details"], {
      cwd: path.resolve(__dirname, "../.."),
      encoding: "utf8",
    });
    expect(output).toContain("./scripts/electron-dev.sh --include-llm-call-details");
  });

  it("forwards a caller-supplied root directory", () => {
    expect(devScriptSource).toContain('ROOT_ARGS+=(--root-directory "$1")');
    expect(backendScriptSource).toContain('ROOT_ARGS+=(--root-directory "$OPENBOT_ROOT_DIRECTORY")');
    expect(mainSource).toContain("OPENBOT_ROOT_DIRECTORY: process.env.OPENBOT_ROOT_DIRECTORY");
    const output = execFileSync("make", ["-n", "electron", "ROOT_DIRECTORY=/tmp/openbot-root"], {
      cwd: path.resolve(__dirname, "../.."),
      encoding: "utf8",
    });
    expect(output).toContain('./scripts/electron-dev.sh  --root-directory "/tmp/openbot-root"');
  });

  it("preserves root-directory argument boundaries when the path contains spaces", () => {
    const output = execFileSync("make", ["-n", "electron", "ROOT_DIRECTORY=/tmp/openbot root"], {
      cwd: path.resolve(__dirname, "../.."),
      encoding: "utf8",
    });
    expect(output).toContain('./scripts/electron-dev.sh  --root-directory "/tmp/openbot root"');
  });

  it("does not manufacture a dangling root flag when no root is supplied", () => {
    const output = execFileSync("make", ["-n", "electron"], {
      cwd: path.resolve(__dirname, "../.."),
      encoding: "utf8",
    });
    expect(output).toContain("./scripts/electron-dev.sh");
    expect(output).toContain(`--root-directory "${path.resolve(__dirname, "../..")}"`);
  });

  it("forwards the parsed root flag to the backend during normal startup", () => {
    expect(devScriptSource).toContain('if [[ "${1:-}" == "--root-directory" ]]');
    expect(devScriptSource).toContain('ROOT_ARGS+=(--root-directory "$2")');
    expect(devScriptSource).toContain('run_in_process_group uv run --project backend python -m openbot.cli "$DETAILS_FLAG"');
  });
});

describe("Electron file watching", () => {
  it("disables backend reload and Vite watching for Electron development", () => {
    expect(devScriptSource).not.toContain("--reload");
    expect(devScriptSource).not.toContain("--reload-dir");
    expect(devScriptSource).toContain('ELECTRON_DEV="1"');
    expect(readFileSync(path.join(__dirname, "../vite.config.ts"), "utf8")).toContain("watch: null");
  });
});

describe("Electron launcher paths", () => {
  it("resolves the repository from the script location when launched elsewhere", () => {
    const output = execFileSync("bash", [devScriptPath], {
      cwd: "/tmp",
      env: { ...process.env, ELECTRON_DEV_PRINT_PATHS: "1" },
      encoding: "utf8",
    });
    expect(output).toContain(`REPO_ROOT=${path.resolve(__dirname, "../..")}`);
  });
});

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
