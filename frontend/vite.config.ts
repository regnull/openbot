import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Which backend the dev proxy forwards /api to: `make dev`'s backend on 8000 by default, or
// whatever port electron-dev.sh's dedicated Electron backend is actually listening on.
const backendPort = process.env.VITE_BACKEND_PORT || "8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true } } },
  test: { environment: "node" },
} as any);
