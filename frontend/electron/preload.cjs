// Minimal bridge: packaged file:// pages need an absolute backend origin, while
// browser/Vite pages continue to use their relative API paths.
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("openbotDesktop", Object.freeze({
  isElectron: true,
  apiBase: process.env.OPENBOT_API_URL || (process.env.OPENBOT_URL?.startsWith("http") ? new URL(process.env.OPENBOT_URL).origin : "http://127.0.0.1:8000"),
}));
