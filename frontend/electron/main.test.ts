import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// main.cjs requires "electron", which only exists inside the Electron runtime, so it can't be
// imported directly in a Vitest run -- assert on its source the same way icon.test.ts does.
const mainSource = readFileSync(path.join(__dirname, "main.cjs"), "utf8");

describe("Electron dev launcher quit behavior", () => {
  it("quits on window-all-closed in development, even on macOS", () => {
    // scripts/electron-dev.sh blocks on this process and only tears down its backend and Vite
    // server once it exits. Standard macOS apps stay running after their last window closes, which
    // would leave that backend/Vite server orphaned forever if this ever regressed.
    expect(mainSource).toMatch(
      /app\.on\("window-all-closed",\s*\(\)\s*=>\s*\{\s*if\s*\(process\.platform !== "darwin" \|\| isDevelopment\)\s*app\.quit\(\);\s*\}\);/,
    );
  });
});
