import { describe, expect, it } from "vitest";
import { REPO_URL, buildApplicationMenuTemplate } from "./menu.cjs";

function labels(items: Array<{ label?: string; role?: string; type?: string }>) {
  return items.map((item) => item.label ?? item.role ?? item.type);
}

describe("application menu template", () => {
  it("includes a macOS app menu with About, Hide and Quit roles", () => {
    const template = buildApplicationMenuTemplate({ platform: "darwin", isDevelopment: false });
    expect(template[0]?.label).toBe("OpenBot");
    expect(labels(template[0].submenu)).toEqual([
      "about",
      "separator",
      "hide",
      "hideOthers",
      "unhide",
      "separator",
      "quit",
    ]);
  });

  it("omits the app menu on Linux", () => {
    const template = buildApplicationMenuTemplate({ platform: "linux", isDevelopment: false });
    expect(template.map((menu: { label: string }) => menu.label)).toEqual(["Edit", "View", "Window", "Help"]);
  });

  it("keeps Edit-menu roles for copy, paste and undo", () => {
    const template = buildApplicationMenuTemplate({ platform: "linux" });
    const edit = template.find((menu: { label: string }) => menu.label === "Edit");
    expect(labels(edit.submenu)).toEqual(["undo", "redo", "separator", "cut", "copy", "paste", "selectAll"]);
  });

  it("exposes reload and DevTools only in development", () => {
    const prod = buildApplicationMenuTemplate({ platform: "linux", isDevelopment: false });
    const dev = buildApplicationMenuTemplate({ platform: "linux", isDevelopment: true });
    const prodView = prod.find((menu: { label: string }) => menu.label === "View").submenu.map((item: { role?: string }) => item.role);
    const devView = dev.find((menu: { label: string }) => menu.label === "View").submenu.map((item: { role?: string }) => item.role);
    expect(prodView).not.toContain("reload");
    expect(prodView).not.toContain("toggleDevTools");
    expect(devView).toContain("reload");
    expect(devView).toContain("toggleDevTools");
  });

  it("points Help at the GitHub repository, not Electron's site", () => {
    const template = buildApplicationMenuTemplate({ platform: "linux" });
    const help = template.find((menu: { label: string }) => menu.label === "Help");
    expect(help.submenu[0].url).toBe(REPO_URL);
    expect(help.submenu[0].url).toContain("github.com/regnull/openbot");
    expect(JSON.stringify(template)).not.toContain("electronjs.org");
  });
});
