const { app, BrowserWindow, session, shell, dialog } = require("electron");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { contentSecurityPolicy, isApprovedExternalUrl, sameOriginOrPackagedPath } = require("./security.cjs");
const { appIconPath } = require("./icon.cjs");
const { resolveApiOrigin } = require("./origin.cjs");

const isDevelopment = !app.isPackaged;
const backendPort = process.env.OPENBOT_BACKEND_PORT || "8000";
const defaultUrl = isDevelopment ? "http://localhost:5173" : `file://${path.join(__dirname, "..", "dist", "index.html")}`;
const appUrl = process.env.OPENBOT_URL || defaultUrl;
const configuredOrigin = new URL(appUrl).origin;
const apiOrigin = resolveApiOrigin();
const usesExternalBackend = Boolean(process.env.OPENBOT_URL || process.env.OPENBOT_API_URL);
const statusPage = path.join(__dirname, "loading.html");
const retryDelayMs = 3000;
let backendProcess;
let quitRequested = false;

function sameOrigin(rawUrl) { return sameOriginOrPackagedPath(rawUrl, appUrl); }
function openApprovedExternal(rawUrl) { if (isApprovedExternalUrl(rawUrl)) { void shell.openExternal(rawUrl); return true; } return false; }
function startBackend() {
  if (isDevelopment || usesExternalBackend) return;
  const script = path.join(process.resourcesPath, "backend", "electron-backend.sh");
  backendProcess = spawn("/bin/sh", [script], { detached: true, env: { ...process.env, OPENBOT_RESOURCES: process.resourcesPath, OPENBOT_USER_DATA: app.getPath("userData"), OPENBOT_BACKEND_PORT: backendPort, OPENBOT_ROOT_DIRECTORY: process.env.OPENBOT_ROOT_DIRECTORY }, stdio: "ignore" });
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
  // can even start listening. That can take well past the ~20s a warm start needs, so budget for
  // a cold one too; later launches reuse that venv and come up in a second or two.
  for (let attempt = 0; attempt < 450; attempt += 1) {
    try { if ((await fetch(healthUrl)).ok) return; } catch { /* backend is still starting */ }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for OpenBot backend at ${healthUrl}`);
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
  if (isDevelopment && process.platform === "darwin") app.dock?.setIcon(appIconPath);
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => callback({ responseHeaders: { ...details.responseHeaders, "Content-Security-Policy": [contentSecurityPolicy(configuredOrigin, apiOrigin)] } }));
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
