// Keep the bridge intentionally empty: the renderer uses the same HTTP/SSE API
// as the browser app and does not need Node or Electron privileges.
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("openbotDesktop", Object.freeze({
  isElectron: true,
}));
