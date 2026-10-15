import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import icon from "./icon.cjs";

const electronDir = path.dirname(icon.appIconPath).replace(/[/\\]assets$/, "");
const frontendDir = path.resolve(electronDir, "..");
const builderConfig = readFileSync(path.resolve(frontendDir, "..", "electron-builder.yml"), "utf8");

function pngSize(file: string) {
  const bytes = readFileSync(file);
  expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

describe("Electron app icon", () => {
  it("is a square PNG large enough for electron-builder's .icns/.ico", () => {
    const { width, height } = pngSize(icon.appIconPath);
    expect(width).toBe(height);
    expect(width).toBeGreaterThanOrEqual(512);
  });

  it("is used for the BrowserWindow and the unpackaged macOS dock", () => {
    const main = readFileSync(path.join(electronDir, "main.cjs"), "utf8");
    expect(main).toContain('require("./icon.cjs")');
    expect(main).toMatch(/new BrowserWindow\(\{[\s\S]*icon: appIconPath/);
    expect(main).toContain("app.dock?.setIcon(appIconPath)");
  });

  it("is the packaging icon and ships inside the packaged files", () => {
    const configured = builderConfig.match(/^icon:\s*(\S+)\s*$/m)?.[1];
    expect(configured).toBeDefined();
    expect(path.resolve(frontendDir, configured!)).toBe(icon.appIconPath);
    expect(builderConfig).toMatch(/^\s+- electron\/\*\*\/\*$/m);
  });
});
