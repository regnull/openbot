const { app, BrowserWindow, session, shell } = require("electron");
const path = require("node:path");
const { contentSecurityPolicy, isApprovedExternalUrl } = require("./security.cjs");

const isDevelopment = !app.isPackaged;
const defaultUrl = isDevelopment
  ? "http://127.0.0.1:5173"
  : `file://${path.join(__dirname, "..", "dist", "index.html")}`;
const appUrl = process.env.OPENBOT_URL || defaultUrl;
const configuredOrigin = new URL(appUrl).origin;
const apiOrigin = process.env.OPENBOT_API_URL ||
  (appUrl.startsWith("http") ? configuredOrigin : "http://127.0.0.1:8000");

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
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({ responseHeaders: { ...details.responseHeaders, "Content-Security-Policy": [contentSecurityPolicy(configuredOrigin, apiOrigin)] } });
  });
  createWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });

module.exports = { createWindow, sameOrigin, openApprovedExternal, apiOrigin };
