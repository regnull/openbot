const { app, BrowserWindow, dialog, Menu, net, protocol, session, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const { contentSecurityPolicy, isApprovedExternalUrl, isSameOrigin, originOf } = require("./security.cjs");
const { appIconPath } = require("./icon.cjs");
const { parseBackendUrl, resolveApiOrigin } = require("./origin.cjs");
const { APP_SCHEME, APP_URL, createAppProtocolHandler, schemePrivileges } = require("./scheme.cjs");
const { UV_MISSING, backendLaunch, findUv } = require("./backend-launcher.cjs");
const { applyApplicationMenu } = require("./menu.cjs");

const isDevelopment = !app.isPackaged;
const backendPort = process.env.OPENBOT_BACKEND_PORT || "8000";
const defaultUrl = isDevelopment ? "http://localhost:5173" : APP_URL;
const appUrl = process.env.OPENBOT_URL || defaultUrl;
const configuredOrigin = originOf(appUrl);
const cliBackendUrl = parseBackendUrl();
const apiOrigin = resolveApiOrigin(undefined, cliBackendUrl);
const usesExternalBackend = Boolean(cliBackendUrl || process.env.OPENBOT_URL || process.env.OPENBOT_API_URL);
// Packaged: serve dist/ and proxy /api from app://openbot (see scheme.cjs). Registration has to
// happen before "ready", and it is harmless when the app ends up loading Vite or OPENBOT_URL.
const servesPackagedUi = appUrl === APP_URL;
const distDir = path.join(__dirname, "..", "dist");
protocol.registerSchemesAsPrivileged(schemePrivileges);
const statusPage = path.join(__dirname, "loading.html");
const retryDelayMs = 3000;
let backendProcess;
let backendStartError;
let quitRequested = false;

function sameOrigin(rawUrl) { return isSameOrigin(rawUrl, appUrl); }
function openApprovedExternal(rawUrl) { if (isApprovedExternalUrl(rawUrl)) { void shell.openExternal(rawUrl); return true; } return false; }
const userDataDir = app.getPath("userData");
const backendLogPath = path.join(userDataDir, "logs", "backend-launcher.log");
function startBackend() {
  if (isDevelopment || usesExternalBackend) return;
  const launch = backendLaunch({ resourcesPath: process.resourcesPath, userDataDir, port: backendPort });
  for (const dir of launch.dirs) fs.mkdirSync(dir, { recursive: true });
  // Keep the backend's output: with stdio ignored, a backend that dies at startup is
  // indistinguishable from one that is slow, and the timeout dialog can point here.
  const log = fs.openSync(backendLogPath, "a");
  const uv = findUv();
  if (!uv) {
    fs.writeSync(log, `${UV_MISSING}
`);
    backendStartError = new Error(`${UV_MISSING} See ${backendLogPath} for details.`);
    return;
  }
  // uv is spawned directly, so no shell is involved on any platform. On macOS and Linux it leads
  // its own process group, which stopBackend signals as a whole; Windows has no process groups.
  backendProcess = spawn(uv, launch.args, { cwd: launch.cwd, env: launch.env, detached: process.platform !== "win32", windowsHide: true, stdio: ["ignore", log, log] });
  backendProcess.unref();
  backendProcess.on("error", (error) => console.error("OpenBot backend failed to start", error));
}
function stopBackend() {
  if (!backendProcess || backendProcess.killed) return;
  if (process.platform === "win32") {
    // uv runs python as a child; /T ends the whole tree, which killing uv alone would not. It has
    // to finish before quitting: Node puts its children in a kill-on-close job, so an async
    // taskkill dies with the app, and uv with it, leaving python orphaned and the port taken.
    spawnSync("taskkill", ["/pid", String(backendProcess.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore", timeout: 10_000 });
  } else {
    try { process.kill(-backendProcess.pid, "SIGTERM"); } catch { backendProcess.kill("SIGTERM"); }
  }
  backendProcess = undefined;
}
async function waitForBackend() {
  if (isDevelopment || usesExternalBackend) return;
  if (backendStartError) throw backendStartError;
  const healthUrl = `${apiOrigin}/api/v1/health`;
  // No .venv ships in the bundle, so the very first launch on a machine has uv build one from
  // scratch -- fetching a matching Python interpreter and every dependency -- before the backend
  // can even start listening. A warm start needs a few seconds; a cold one on a slow machine or
  // connection can take many minutes, so budget by whether the venv already exists.
  const coldStart = !fs.existsSync(path.join(userDataDir, "venv"));
  const deadline = Date.now() + (coldStart ? 15 * 60_000 : 90_000);
  while (Date.now() < deadline) {
    try { if ((await fetch(healthUrl)).ok) return; } catch { /* backend is still starting */ }
    if (backendProcess?.exitCode != null) break;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  const why = backendProcess?.exitCode != null ? `The backend exited with code ${backendProcess.exitCode}` : `Timed out waiting for OpenBot backend at ${healthUrl}`;
  throw new Error(`${why}. See ${backendLogPath} for its output.`);
}
/** Show the local status page (#starting or #unavailable); it has no scripts and needs no preload. */
function showStatus(window, state) {
  // Loading the app replaces this page, which rejects the promise with ERR_ABORTED; that is expected.
  if (!window.isDestroyed()) window.loadFile(statusPage, { hash: state }).catch(() => {});
}
function loadApp(window) {
  // A failed load is reported through did-fail-load, which shows the status page and retries.
  if (!window.isDestroyed()) window.loadURL(appUrl).catch(() => {});
}
function createWindow({ waitingForBackend = false } = {}) {
  const window = new BrowserWindow({ width: 1440, height: 900, minWidth: 900, minHeight: 600, backgroundColor: "#111827", icon: appIconPath, webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  window.webContents.setWindowOpenHandler(({ url }) => { if (sameOrigin(url)) return { action: "allow" }; openApprovedExternal(url); return { action: "deny" }; });
  window.webContents.on("will-navigate", (event, url) => { if (sameOrigin(url)) return; event.preventDefault(); openApprovedExternal(url); });
  // A failed app load (Vite not up yet, OPENBOT_URL unreachable) otherwise leaves a blank window.
  // ERR_ABORTED (-3) is a navigation superseded by another one, not a failure.
  window.webContents.on("did-fail-load", (_event, errorCode, _description, url, isMainFrame) => {
    if (!isMainFrame || errorCode === -3 || !sameOrigin(url)) return;
    showStatus(window, "unavailable");
    setTimeout(() => loadApp(window), retryDelayMs);
  });
  if (waitingForBackend) showStatus(window, "starting");
  else loadApp(window);
  return window;
}
app.whenReady().then(async () => {
  app.setName("OpenBot");
  applyApplicationMenu(Menu, shell, { platform: process.platform, isDevelopment });
  if (isDevelopment && process.platform === "darwin") app.dock?.setIcon(appIconPath);
  const csp = contentSecurityPolicy(configuredOrigin, apiOrigin);
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => callback({ responseHeaders: { ...details.responseHeaders, "Content-Security-Policy": [csp] } }));
  if (servesPackagedUi) protocol.handle(APP_SCHEME, createAppProtocolHandler({ apiOrigin, distDir, net }));
  startBackend();
  // Open the window right away so the wait is visible: a cold first launch can spend a long
  // time building the backend venv before /api/v1/health answers.
  const waitingForBackend = !isDevelopment && !usesExternalBackend;
  const window = createWindow({ waitingForBackend });
  try {
    await waitForBackend();
    if (waitingForBackend) loadApp(window);
  } catch (error) {
    console.error(error);
    // Without this, a backend that never comes up (missing uv, a build failure, ...) just made
    // the app quit with no window and nothing visible -- indistinguishable from it not launching
    // at all. Show the operator what actually happened before giving up.
    dialog.showErrorBox("OpenBot backend failed to start", error instanceof Error ? error.message : String(error));
    app.quit();
  }
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on("before-quit", () => { if (!quitRequested) { quitRequested = true; stopBackend(); } });
app.on("window-all-closed", () => { if (process.platform !== "darwin" || isDevelopment) app.quit(); });
module.exports = { createWindow, sameOrigin, openApprovedExternal, apiOrigin, startBackend, stopBackend, waitForBackend };
