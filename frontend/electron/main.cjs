const { app, BrowserWindow, session } = require("electron");
const path = require("node:path");

const isDevelopment = !app.isPackaged;
const defaultUrl = isDevelopment
  ? "http://127.0.0.1:5173"
  : `file://${path.join(__dirname, "..", "dist", "index.html")}`;
const appUrl = process.env.OPENBOT_URL || defaultUrl;
const configuredOrigin = new URL(appUrl).origin;

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#111827",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Keep navigation inside the configured OpenBot origin. External links are
  // deliberately left to the user's browser rather than granting the renderer
  // access to Electron or arbitrary origins.
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (new URL(url).origin === configuredOrigin) return { action: "allow" };
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (new URL(url).origin !== configuredOrigin) event.preventDefault();
  });
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [
          "default-src 'self' ${configuredOrigin}; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self' ${configuredOrigin}",
        ],
      },
    });
  });
  window.loadURL(appUrl);
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
