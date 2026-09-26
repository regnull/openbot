const { app, BrowserWindow, dialog, net, protocol, session, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { contentSecurityPolicy, isApprovedExternalUrl, isSameOrigin, originOf } = require("./security.cjs");
const { appIconPath } = require("./icon.cjs");
const { resolveApiOrigin } = require("./origin.cjs");
const { APP_SCHEME, APP_URL, createAppProtocolHandler, schemePrivileges } = require("./scheme.cjs");

const isDevelopment = !app.isPackaged;
const backendPort = process.env.OPENBOT_BACKEND_PORT || "8000";
const defaultUrl = isDevelopment ? "http://localhost:5173" : APP_URL;
const appUrl = process.env.OPENBOT_URL || defaultUrl;
const configuredOrigin = originOf(appUrl);
const apiOrigin = resolveApiOrigin();
const usesExternalBackend = Boolean(process.env.OPENBOT_URL || process.env.OPENBOT_API_URL);
// Packaged: serve dist/ and proxy /api from app://openbot (see scheme.cjs). Registration has to
// happen before "ready", and it is harmless when the app ends up loading Vite or OPENBOT_URL.
const servesPackagedUi = appUrl === APP_URL;
const distDir = path.join(__dirname, "..", "dist");
protocol.registerSchemesAsPrivileged(schemePrivileges);
let backendProcess;
let quitRequested = false;

function sameOrigin(rawUrl) { return isSameOrigin(rawUrl, appUrl); }
function openApprovedExternal(rawUrl) { if (isApprovedExternalUrl(rawUrl)) { void shell.openExternal(rawUrl); return true; } return false; }
const userDataDir = app.getPath("userData");
const backendLogPath = path.join(userDataDir, "logs", "backend-launcher.log");
function startBackend() {
  if (isDevelopment || usesExternalBackend) return;
  const script = path.join(process.resourcesPath, "backend", "electron-backend.sh");
  // The script is bash (`[[`, arrays, `set -E`), and /bin/sh is dash on Debian and Ubuntu, so
  // it must be run by bash explicitly. Keep its output: with stdio ignored, a backend that dies
  // at startup is indistinguishable from one that is slow, and the timeout dialog can point here.
  fs.mkdirSync(path.dirname(backendLogPath), { recursive: true });
  const log = fs.openSync(backendLogPath, "a");
  backendProcess = spawn("/bin/bash", [script], { detached: true, env: { ...process.env, OPENBOT_RESOURCES: process.resourcesPath, OPENBOT_USER_DATA: userDataDir, OPENBOT_BACKEND_PORT: backendPort, OPENBOT_ROOT_DIRECTORY: process.env.OPENBOT_ROOT_DIRECTORY }, stdio: ["ignore", log, log] });
  backendProcess.unref();
  backendProcess.on("error", (error) => console.error("OpenBot backend failed to start", error));
}
function stopBackend() {
  if (!backendProcess || backendProcess.killed) return;
  try { process.kill(-backendProcess.pid, "SIGTERM"); } catch { backendProcess.kill("SIGTERM"); }
  backendProcess = undefined;
}
async function waitForBackend() {
  if (isDevelopment || usesExternalBackend) return;
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
function createWindow() {
  const window = new BrowserWindow({ width: 1440, height: 900, minWidth: 900, minHeight: 600, backgroundColor: "#111827", icon: appIconPath, webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  window.webContents.setWindowOpenHandler(({ url }) => { if (sameOrigin(url)) return { action: "allow" }; openApprovedExternal(url); return { action: "deny" }; });
  window.webContents.on("will-navigate", (event, url) => { if (sameOrigin(url)) return; event.preventDefault(); openApprovedExternal(url); });
  window.loadURL(appUrl);
}
app.whenReady().then(async () => {
  if (isDevelopment && process.platform === "darwin") app.dock?.setIcon(appIconPath);
  const csp = contentSecurityPolicy(configuredOrigin, apiOrigin);
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => callback({ responseHeaders: { ...details.responseHeaders, "Content-Security-Policy": [csp] } }));
  if (servesPackagedUi) protocol.handle(APP_SCHEME, createAppProtocolHandler({ apiOrigin, distDir, net }));
  startBackend();
  try {
    await waitForBackend();
    createWindow();
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
