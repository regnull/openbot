import { describe, expect, it } from "vitest";
import { backendLaunch, findUv, sqliteUrl } from "./backend-launcher.cjs";

const only = (...files: string[]) => (file: string) => files.includes(file);

describe("findUv", () => {
  it("prefers uv on the inherited PATH, using PATHEXT on Windows", () => {
    const env = { PATH: "C:\\Tools;C:\\uv", PATHEXT: ".COM;.EXE;.BAT" };
    expect(findUv({ platform: "win32", env, homedir: "C:\\Users\\ada", canRun: only("C:\\uv\\uv.exe") })).toBe("C:\\uv\\uv.exe");
  });

  it("reads Windows' Path spelling of the variable", () => {
    const env = { Path: "C:\\uv", PATHEXT: ".EXE" };
    expect(findUv({ platform: "win32", env, homedir: "C:\\Users\\ada", canRun: only("C:\\uv\\uv.exe") })).toBe("C:\\uv\\uv.exe");
  });

  it("finds uv's own Windows install dir when PATH misses it", () => {
    const home = "C:\\Users\\ada";
    expect(findUv({ platform: "win32", env: { PATH: "" }, homedir: home, canRun: only(`${home}\\.local\\bin\\uv.exe`) }))
      .toBe(`${home}\\.local\\bin\\uv.exe`);
  });

  it("finds WinGet and Scoop installs on Windows", () => {
    const home = "C:\\Users\\ada";
    const local = "C:\\Users\\ada\\AppData\\Local";
    const winget = `${local}\\Microsoft\\WinGet\\Links\\uv.exe`;
    expect(findUv({ platform: "win32", env: { LOCALAPPDATA: local }, homedir: home, canRun: only(winget) })).toBe(winget);
    expect(findUv({ platform: "win32", env: {}, homedir: home, canRun: only(`${home}\\scoop\\shims\\uv.exe`) }))
      .toBe(`${home}\\scoop\\shims\\uv.exe`);
  });

  it("checks the user-local and Homebrew locations on macOS and Linux", () => {
    expect(findUv({ platform: "darwin", env: { PATH: "/usr/bin:/bin" }, homedir: "/Users/ada", canRun: only("/opt/homebrew/bin/uv") }))
      .toBe("/opt/homebrew/bin/uv");
    expect(findUv({ platform: "linux", env: { PATH: "/usr/bin" }, homedir: "/home/ada", canRun: only("/home/ada/.local/bin/uv") }))
      .toBe("/home/ada/.local/bin/uv");
    expect(findUv({ platform: "linux", env: { PATH: "/usr/bin:/opt/uv" }, homedir: "/home/ada", canRun: only("/opt/uv/uv", "/home/ada/.local/bin/uv") }))
      .toBe("/opt/uv/uv");
  });

  it("returns null when uv is nowhere", () => {
    expect(findUv({ platform: "win32", env: { PATH: "C:\\Windows" }, homedir: "C:\\Users\\ada", canRun: () => false })).toBeNull();
    expect(findUv({ platform: "linux", env: { PATH: "/usr/bin" }, homedir: "/home/ada", canRun: () => false })).toBeNull();
  });
});

describe("backendLaunch", () => {
  const unix = { resourcesPath: "/opt/OpenBot/resources", userDataDir: "/home/ada/.config/OpenBot", port: "8000", platform: "linux" };

  it("keeps data, workspace, logs and the venv in the app's data directory by default", () => {
    const launch = backendLaunch({ ...unix, env: {} });
    expect(launch.cwd).toBe("/opt/OpenBot/resources");
    expect(launch.env.DATABASE_URL).toBe("sqlite+aiosqlite:////home/ada/.config/OpenBot/openbot.db");
    expect(launch.env.WORKSPACE_ROOT).toBe("/home/ada/.config/OpenBot/workspace");
    expect(launch.env.SECRET_KEY_FILE).toBe("/home/ada/.config/OpenBot/secret.key");
    expect(launch.env.TOOLS_DIR).toBe("/opt/OpenBot/resources/tools");
    expect(launch.env.LOG_FILE).toBe("/home/ada/.config/OpenBot/logs/openbot.log");
    expect(launch.env.UV_PROJECT_ENVIRONMENT).toBe("/home/ada/.config/OpenBot/venv");
    expect(launch.env.OPENBOT_USER_DATA).toBe("/home/ada/.config/OpenBot");
    expect(launch.dirs).toEqual(["/home/ada/.config/OpenBot/logs", "/home/ada/.config/OpenBot/workspace"]);
    expect(launch.args).toEqual(["run", "--project", "/opt/OpenBot/resources/backend", "python", "-m", "openbot.cli",
      "--exclude-llm-call-details", "--host", "127.0.0.1", "--port", "8000"]);
  });

  it("lets values from the environment win, except the venv location", () => {
    const env = { DATABASE_URL: "postgresql://db/openbot", WORKSPACE_ROOT: "/srv/ws", SECRET_KEY_FILE: "/etc/openbot/secret.key", TOOLS_DIR: "/srv/tools", LOG_FILE: "/var/log/openbot.log", UV_PROJECT_ENVIRONMENT: "/tmp/elsewhere" };
    const launch = backendLaunch({ ...unix, env });
    expect(launch.env.DATABASE_URL).toBe("postgresql://db/openbot");
    expect(launch.env.WORKSPACE_ROOT).toBe("/srv/ws");
    expect(launch.env.SECRET_KEY_FILE).toBe("/etc/openbot/secret.key");
    expect(launch.env.TOOLS_DIR).toBe("/srv/tools");
    expect(launch.env.LOG_FILE).toBe("/var/log/openbot.log");
    // The app's resources are not reliably writable once installed, so the venv always goes to app data.
    expect(launch.env.UV_PROJECT_ENVIRONMENT).toBe("/home/ada/.config/OpenBot/venv");
  });

  it("leaves database and workspace to the backend when a root directory is chosen", () => {
    const launch = backendLaunch({ ...unix, env: { OPENBOT_ROOT_DIRECTORY: "/home/ada/bots" } });
    expect(launch.env.DATABASE_URL).toBeUndefined();
    expect(launch.env.WORKSPACE_ROOT).toBeUndefined();
    expect(launch.env.SECRET_KEY_FILE).toBeUndefined();          // the backend puts it under <root>/.openbot
    expect(launch.dirs).toEqual(["/home/ada/.config/OpenBot/logs", "/home/ada/bots", "/home/ada/bots/.openbot"]);
    expect(launch.args).toContain("--root-directory");
    expect(launch.args[launch.args.indexOf("--root-directory") + 1]).toBe("/home/ada/bots");
  });

  it("forwards the LLM call details opt-in", () => {
    expect(backendLaunch({ ...unix, env: { OPENBOT_INCLUDE_LLM_CALL_DETAILS: "true" } }).args).toContain("--include-llm-call-details");
  });

  it("builds Windows paths and a forward-slash SQLite URL", () => {
    const launch = backendLaunch({
      resourcesPath: "C:\\Program Files\\OpenBot\\resources", userDataDir: "C:\\Users\\ada\\AppData\\Roaming\\OpenBot",
      port: "8000", platform: "win32", env: {},
    });
    expect(launch.env.DATABASE_URL).toBe("sqlite+aiosqlite:///C:/Users/ada/AppData/Roaming/OpenBot/openbot.db");
    expect(launch.env.UV_PROJECT_ENVIRONMENT).toBe("C:\\Users\\ada\\AppData\\Roaming\\OpenBot\\venv");
    expect(launch.env.SECRET_KEY_FILE).toBe("C:\\Users\\ada\\AppData\\Roaming\\OpenBot\\secret.key");
    expect(launch.args[2]).toBe("C:\\Program Files\\OpenBot\\resources\\backend");
  });

  it("formats SQLite URLs for both path styles", () => {
    expect(sqliteUrl("/home/ada/openbot.db")).toBe("sqlite+aiosqlite:////home/ada/openbot.db");
    expect(sqliteUrl("C:\\data\\openbot.db")).toBe("sqlite+aiosqlite:///C:/data/openbot.db");
  });
});
