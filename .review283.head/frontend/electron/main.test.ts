import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(path.join(__dirname, "main.cjs"), "utf8");
const builderSource = readFileSync(path.join(__dirname, "../../electron-builder.yml"), "utf8");
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
    expect(output).not.toContain("--root-directory");
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

describe("Electron application menu", () => {
  it("installs an explicit application menu instead of Electron's default", () => {
    expect(mainSource).toContain("applyApplicationMenu(Menu, shell");
    expect(mainSource).toContain('app.setName("OpenBot")');
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

  it("keeps tests and a developer's local state out of the bundled backend", () => {
    for (const excluded of ["tests/**", ".openbot/**", "workspace/**", "secret.key", "mcp_token.key", ".env", "mcp.json"]) {
      expect(builderSource).toContain(`- "!${excluded}"`);
    }
  });

  it("waits for backend health and terminates its process group", () => {
    expect(mainSource).toContain("/api/v1/health");
    expect(mainSource).toContain("process.kill(-backendProcess.pid, \"SIGTERM\")");
    expect(mainSource).toContain("await waitForBackend();");
  });

  it("spawns uv directly, without a shell, so the launcher also works on Windows", () => {
    expect(mainSource).toContain("spawn(uv, launch.args, { cwd: launch.cwd, env: launch.env");
    expect(mainSource).not.toContain('spawn("/bin/bash"');
    expect(mainSource).not.toContain('spawn("/bin/sh"');
    expect(builderSource).not.toContain("electron-backend.sh");
  });

  it("ends the whole backend tree on Windows, which has no process groups", () => {
    // Synchronously: Node's kill-on-close job would end an async taskkill together with the app.
    expect(mainSource).toContain('spawnSync("taskkill", ["/pid", String(backendProcess.pid), "/T", "/F"]');
  });

  it("explains a missing uv in the startup error instead of a bare exit code", () => {
    expect(mainSource).toContain("backendStartError = new Error(`${UV_MISSING}");
    expect(mainSource).toContain("if (backendStartError) throw backendStartError;");
  });

  it("keeps the backend's output and names the log in the startup error", () => {
    expect(mainSource).toContain('stdio: ["ignore", log, log]');
    expect(mainSource).toContain("See ${backendLogPath} for its output.");
  });

  it("gives a cold first launch, which builds the venv, a longer budget than a warm one", () => {
    expect(mainSource).toContain('const coldStart = !fs.existsSync(path.join(userDataDir, "venv"));');
    expect(mainSource).toContain("coldStart ? 15 * 60_000 : 90_000");
  });

  it("names the app so its data directory is OpenBot, not the package name", () => {
    // app.getPath("userData") derives from productName; without it the venv, database and logs
    // land in ~/.config/frontend (Linux) or Application Support/frontend (macOS).
    const packageJson = JSON.parse(readFileSync(path.join(__dirname, "../package.json"), "utf8"));
    expect(packageJson.productName).toBe("OpenBot");
    expect(builderSource).toContain("productName: OpenBot");
  });

  it("names the package so installs are not called frontend", () => {
    // electron-builder takes the package name, not productName, for the per-user Windows install
    // folder (%LOCALAPPDATA%\Programs\<name>) and the Linux executable.
    const packageJson = JSON.parse(readFileSync(path.join(__dirname, "../package.json"), "utf8"));
    expect(packageJson.name).toBe("openbot");
  });

    it("skips bundled backend startup and readiness for explicit API, remote URLs, or --backend_url", () => {
    expect(mainSource).toContain("const usesExternalBackend = Boolean(cliBackendUrl || process.env.OPENBOT_URL || process.env.OPENBOT_API_URL);");
    expect(mainSource).toContain("if (isDevelopment || usesExternalBackend) return;");
    expect(mainSource).toContain("if (isDevelopment || usesExternalBackend) return;\n  if (backendStartError) throw backendStartError;\n  const healthUrl");
  });

  it("parses --backend_url from the command line and passes it to resolveApiOrigin", () => {
    expect(mainSource).toContain("const cliBackendUrl = parseBackendUrl();");
    expect(mainSource).toContain("resolveApiOrigin(undefined, cliBackendUrl)");
    expect(mainSource).toContain('const { parseBackendUrl, resolveApiOrigin } = require("./origin.cjs")');
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
});

describe("Electron status page", () => {
  const statusSource = readFileSync(path.join(__dirname, "loading.html"), "utf8");

  it("is a static page with a locked-down CSP", () => {
    expect(statusSource).toContain(`content="default-src 'none'; style-src 'unsafe-inline'"`);
    expect(statusSource).not.toMatch(/<script/i);
    expect(statusSource).toContain('id="starting"');
    expect(statusSource).toContain('id="unavailable"');
  });

  it("opens the window before waiting for the backend", () => {
    expect(mainSource.indexOf("createWindow({ waitingForBackend })")).toBeGreaterThan(-1);
    expect(mainSource.indexOf("createWindow({ waitingForBackend })")).toBeLessThan(mainSource.indexOf("await waitForBackend()"));
    expect(mainSource).toContain('showStatus(window, "starting")');
  });

  it("shows the retry state instead of a blank window when the app fails to load", () => {
    expect(mainSource).toContain('"did-fail-load"');
    expect(mainSource).toContain('showStatus(window, "unavailable")');
  });

  it("is packaged with the Electron files", () => {
    expect(builderSource).toContain("electron/**/*");
  });
});
