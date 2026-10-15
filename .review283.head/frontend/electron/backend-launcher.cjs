// How the packaged app starts its bundled backend: find uv, then build the command line,
// working directory and environment for `uv run ... openbot.cli`. Plain Node so it behaves the
// same on macOS, Linux and Windows; file checks are injectable for the unit tests.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const UV_MISSING = "OpenBot requires uv to run its bundled backend. Install uv from https://docs.astral.sh/uv/";

function pathFor(platform) {
  return platform === "win32" ? path.win32 : path.posix;
}

function isRunnable(file, platform) {
  try {
    fs.accessSync(file, platform === "win32" ? fs.constants.F_OK : fs.constants.X_OK);
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

/** Every place uv may live, in lookup order: the inherited PATH first, then common install dirs. */
function uvCandidates({ platform = process.platform, env = process.env, homedir = os.homedir() } = {}) {
  const p = pathFor(platform);
  const names = platform === "win32"
    ? (env.PATHEXT || ".COM;.EXE;.BAT;.CMD").split(";").filter(Boolean).map((ext) => `uv${ext.toLowerCase()}`)
    : ["uv"];
  const dirs = (env.PATH ?? env.Path ?? "").split(p.delimiter).filter(Boolean);
  const fromPath = dirs.flatMap((dir) => names.map((name) => p.join(dir, name)));
  // A GUI-launched app (double-clicked, not run from a terminal) gets a minimal PATH that misses
  // user-local installs, so check where uv's own installer and common package managers put it.
  const fallbacks = platform === "win32"
    ? [
        p.join(homedir, ".local", "bin", "uv.exe"),
        p.join(homedir, ".cargo", "bin", "uv.exe"),
        ...(env.LOCALAPPDATA ? [p.join(env.LOCALAPPDATA, "Microsoft", "WinGet", "Links", "uv.exe")] : []),
        p.join(homedir, "scoop", "shims", "uv.exe"),
      ]
    : [p.join(homedir, ".local", "bin", "uv"), p.join(homedir, ".cargo", "bin", "uv"), "/opt/homebrew/bin/uv", "/usr/local/bin/uv"];
  return [...fromPath, ...fallbacks];
}

function findUv({ platform = process.platform, env = process.env, homedir = os.homedir(), canRun = (file) => isRunnable(file, platform) } = {}) {
  return uvCandidates({ platform, env, homedir }).find((file) => canRun(file)) ?? null;
}

/** SQLAlchemy wants forward slashes, also for a Windows drive path (sqlite+aiosqlite:///C:/...). */
function sqliteUrl(file) {
  return `sqlite+aiosqlite:///${file.replace(/\\/g, "/")}`;
}

/**
 * The directories to create, the working directory, the environment and the `uv` arguments for
 * the bundled backend. Values the user already set in the environment win, except
 * UV_PROJECT_ENVIRONMENT: `uv run --project` would otherwise build the venv inside the app's
 * resources, which an installed (and on macOS signed) app cannot reliably write to.
 */
function backendLaunch({ resourcesPath, userDataDir, port = "8000", env = process.env, platform = process.platform }) {
  const p = pathFor(platform);
  const rootDirectory = env.OPENBOT_ROOT_DIRECTORY || "";
  const launchEnv = { ...env, OPENBOT_RESOURCES: resourcesPath, OPENBOT_USER_DATA: userDataDir, OPENBOT_BACKEND_PORT: port };
  const dirs = [p.join(userDataDir, "logs")];
  if (rootDirectory) {
    dirs.push(rootDirectory, p.join(rootDirectory, ".openbot"));
  } else {
    dirs.push(p.join(userDataDir, "workspace"));
    launchEnv.DATABASE_URL = env.DATABASE_URL || sqliteUrl(p.join(userDataDir, "openbot.db"));
    launchEnv.WORKSPACE_ROOT = env.WORKSPACE_ROOT || p.join(userDataDir, "workspace");
    // Next to the database it protects. The backend runs with the install's resources as its working
    // directory, so the default ./secret.key landed there, and every update replaced that folder.
    launchEnv.SECRET_KEY_FILE = env.SECRET_KEY_FILE || p.join(userDataDir, "secret.key");
  }
  launchEnv.TOOLS_DIR = env.TOOLS_DIR || p.join(resourcesPath, "tools");
  launchEnv.LOG_FILE = env.LOG_FILE || p.join(userDataDir, "logs", "openbot.log");
  launchEnv.UV_PROJECT_ENVIRONMENT = p.join(userDataDir, "venv");
  // No .venv ships in the bundle (see electron-builder.yml): a venv uv builds has absolute paths
  // back to wherever it was built. `uv run` builds one rooted in this installed copy instead.
  const details = env.OPENBOT_INCLUDE_LLM_CALL_DETAILS === "true" ? "--include-llm-call-details" : "--exclude-llm-call-details";
  const args = ["run", "--project", p.join(resourcesPath, "backend"), "python", "-m", "openbot.cli", details,
    ...(rootDirectory ? ["--root-directory", rootDirectory] : []), "--host", "127.0.0.1", "--port", String(port)];
  return { cwd: resourcesPath, dirs, env: launchEnv, args };
}

module.exports = { UV_MISSING, backendLaunch, findUv, sqliteUrl, uvCandidates };
