const { app, BrowserWindow, session, shell } = require("electron");
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
let backendProcess;
let quitRequested = false;

function sameOrigin(rawUrl) { return sameOriginOrPackagedPath(rawUrl, appUrl); }
function openApprovedExternal(rawUrl) { if (isApprovedExternalUrl(rawUrl)) { void shell.openExternal(rawUrl); return true; } return false; }
function startBackend() {
  if (isDevelopment || usesExternalBackend) return;
  const script = path.join(process.resourcesPath, "backend", "electron-backend.sh");
  backendProcess = spawn("/bin/sh", [script], { detached: true, env: { ...process.env, OPENBOT_RESOURCES: process.resourcesPath, OPENBOT_USER_DATA: app.getPath("userData"), OPENBOT_BACKEND_PORT: backendPort }, stdio: "ignore" });
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
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try { if ((await fetch(healthUrl)).ok) return; } catch { /* backend is still starting */ }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for OpenBot backend at ${healthUrl}`);
}
function createWindow() {
  const window = new BrowserWindow({ width: 1440, height: 900, minWidth: 900, minHeight: 600, backgroundColor: "#111827", icon: appIconPath, webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  window.webContents.setWindowOpenHandler(({ url }) => { if (sameOrigin(url)) return { action: "allow" }; openApprovedExternal(url); return { action: "deny" }; });
  window.webContents.on("will-navigate", (event, url) => { if (sameOrigin(url)) return; event.preventDefault(); openApprovedExternal(url); });
  window.loadURL(appUrl);
}
app.whenReady().then(async () => {
  if (isDevelopment && process.platform === "darwin") app.dock?.setIcon(appIconPath);
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => callback({ responseHeaders: { ...details.responseHeaders, "Content-Security-Policy": [contentSecurityPolicy(configuredOrigin, apiOrigin)] } }));
  startBackend();
  try { await waitForBackend(); createWindow(); } catch (error) { console.error(error); app.quit(); }
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on("before-quit", () => { if (!quitRequested) { quitRequested = true; stopBackend(); } });
app.on("window-all-closed", () => { if (process.platform !== "darwin" || isDevelopment) app.quit(); });
module.exports = { createWindow, sameOrigin, openApprovedExternal, apiOrigin, startBackend, stopBackend, waitForBackend };
