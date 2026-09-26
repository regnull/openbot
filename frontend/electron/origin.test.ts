import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { apiBaseArgument, resolveApiOrigin } from "./origin.cjs";

describe("Electron API origin", () => {
  it("uses the configured backend port by default", () => {
    expect(resolveApiOrigin({ OPENBOT_BACKEND_PORT: "8123" })).toBe("http://127.0.0.1:8123");
    expect(resolveApiOrigin({})).toBe("http://127.0.0.1:8000");
  });

  it("prefers explicit API and remote deployment URLs", () => {
    expect(resolveApiOrigin({ OPENBOT_API_URL: "http://api.example.test:9000" })).toBe("http://api.example.test:9000");
    expect(resolveApiOrigin({ OPENBOT_URL: "https://openbot.example.test/workspace" })).toBe("https://openbot.example.test");
  });
});

describe("Electron preload bridge", () => {
  const preloadSource = readFileSync(path.join(__dirname, "preload.cjs"), "utf8");
  const mainSource = readFileSync(path.join(__dirname, "main.cjs"), "utf8");
  const packageJson = JSON.parse(readFileSync(path.join(__dirname, "../package.json"), "utf8"));

  it("does not require local modules, which the sandboxed preload cannot load", () => {
    expect(preloadSource).not.toMatch(/require\(["']\.{1,2}\//);
  });

  it("receives the API origin from main as a process argument", () => {
    expect(preloadSource).toContain(`"${apiBaseArgument}"`);
    expect(mainSource).toContain("additionalArguments: [`${apiBaseArgument}${apiOrigin}`]");
  });

  it("builds the packaged UI with relative asset URLs for file://", () => {
    expect(packageJson.scripts["build:electron"]).toContain("--base ./");
    expect(packageJson.scripts["electron:package"]).toContain("pnpm build:electron");
  });
});
