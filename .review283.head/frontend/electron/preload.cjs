// The window is sandboxed, so this preload can only require "electron": a require of a local
// module fails and silently drops the whole bridge. Keep it dependency-free.
// The packaged app is served from app://openbot with /api proxied by main (see scheme.cjs), so the
// renderer uses the same relative API paths as the browser build and needs no backend origin here.
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("openbotDesktop", Object.freeze({ isElectron: true }));
