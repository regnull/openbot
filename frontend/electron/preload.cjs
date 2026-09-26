// Minimal bridge: packaged file:// pages need an absolute backend origin, while
// browser/Vite pages continue to use their relative API paths.
// The window is sandboxed, so this preload can only require "electron"; a local
// require of origin.cjs fails and drops the whole bridge. main.cjs resolves the
// origin and passes it as --openbot-api-base=<origin> (see origin.cjs).
const { contextBridge } = require("electron");

const prefix = "--openbot-api-base=";
const arg = process.argv.find((a) => a.startsWith(prefix));

contextBridge.exposeInMainWorld("openbotDesktop", Object.freeze({
  isElectron: true,
  apiBase: arg ? arg.slice(prefix.length) : undefined,
}));
