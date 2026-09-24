const { app, BrowserWindow, session, shell } = require("electron");
const path = require("node:path");
const { contentSecurityPolicy, isApprovedExternalUrl } = require("./security.cjs");
const { appIconPath } = require("./icon.cjs");

const isDevelopment = !app.isPackaged;
const defaultUrl = isDevelopment
  ? "http://localhost:5173"
  : `file://${path.join(__dirname, "..", "dist", "index.html")}`;
const appUrl = process.env.OPENBOT_URL || defaultUrl;
const configuredOrigin = new URL(appUrl).origin;
// Matches preload.cjs's apiBase default: relies on OPENBOT_URL (not the
// already-defaulted appUrl) so the CSP's connect-src stays in sync with
// where the renderer actually fetches the API from.
const apiOrigin = process.env.OPENBOT_API_URL ||
  (process.env.OPENBOT_URL?.startsWith("http") ? configuredOrigin : "http://127.0.0.1:8000");

function sameOrigin(rawUrl) {
  try { return new URL(rawUrl).origin === configuredOrigin; } catch { return false; }
}
function openApprovedExternal(rawUrl) {
  if (isApprovedExternalUrl(rawUrl)) { void shell.openExternal(rawUrl); return true; }
  return false;
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1440, height: 900, minWidth: 900, minHeight: 600,
    backgroundColor: "#111827",
    icon: appIconPath,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (sameOrigin(url)) return { action: "allow" };
    openApprovedExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (sameOrigin(url)) return;
    event.preventDefault();
    openApprovedExternal(url);
  });
  window.loadURL(appUrl);
}

app.whenReady().then(() => {
  // macOS ignores BrowserWindow.icon; packaged builds get the .icns from
  // electron-builder, so only the unpackaged dock needs setting.
  if (isDevelopment && process.platform === "darwin") app.dock?.setIcon(appIconPath);
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({ responseHeaders: { ...details.responseHeaders, "Content-Security-Policy": [contentSecurityPolicy(configuredOrigin, apiOrigin)] } });
  });
  createWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });

module.exports = { createWindow, sameOrigin, openApprovedExternal, apiOrigin };
