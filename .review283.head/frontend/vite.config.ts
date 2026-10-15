import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Which backend the dev proxy forwards /api to: `make dev`'s backend on 8000 by default, or
// whatever port electron-dev.sh's dedicated Electron backend is actually listening on.
const backendPort = process.env.VITE_BACKEND_PORT || "8000";
const isElectronDev = process.env.ELECTRON_DEV === "1";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Electron development is intentionally restart-to-update: Vite's watcher can consume
    // enough resources during repository changes to freeze the UI while sending messages.
    ...(isElectronDev ? { watch: null } : {}),
    proxy: { "/api": { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true } },
  },
  test: { environment: "node" },
} as any);
