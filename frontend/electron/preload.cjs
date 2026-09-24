// Minimal bridge: packaged file:// pages need an absolute backend origin, while
// browser/Vite pages continue to use their relative API paths.
const { contextBridge } = require("electron");
const { resolveApiOrigin } = require("./origin.cjs");

contextBridge.exposeInMainWorld("openbotDesktop", Object.freeze({
  isElectron: true,
  apiBase: resolveApiOrigin(),
}));

module.exports = { resolveApiOrigin };
