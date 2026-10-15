const REPO_URL = "https://github.com/regnull/openbot";

/**
 * Build the application menu template from Electron roles.
 * Kept free of the Electron module so unit tests can assert structure.
 */
function buildApplicationMenuTemplate({ platform = process.platform, isDevelopment = false, repoUrl = REPO_URL } = {}) {
  const isMac = platform === "darwin";
  const template = [];

  if (isMac) {
    template.push({
      label: "OpenBot",
      submenu: [
        { role: "about" },
        { type: "separator" },
        { role: "hide" },
        { role: "hideOthers" },
        { role: "unhide" },
        { type: "separator" },
        { role: "quit" },
      ],
    });
  }

  template.push({
    label: "Edit",
    submenu: [
      { role: "undo" },
      { role: "redo" },
      { type: "separator" },
      { role: "cut" },
      { role: "copy" },
      { role: "paste" },
      { role: "selectAll" },
    ],
  });

  const viewSubmenu = [];
  if (isDevelopment) {
    viewSubmenu.push({ role: "reload" }, { role: "toggleDevTools" }, { type: "separator" });
  }
  viewSubmenu.push({ role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { type: "separator" }, { role: "togglefullscreen" });
  template.push({ label: "View", submenu: viewSubmenu });

  template.push({
    label: "Window",
    submenu: isMac
      ? [{ role: "minimize" }, { role: "zoom" }, { type: "separator" }, { role: "front" }]
      : [{ role: "minimize" }, { role: "close" }],
  });

  template.push({
    label: "Help",
    submenu: [
      {
        label: "OpenBot on GitHub",
        url: repoUrl,
      },
    ],
  });

  return template;
}

function applyApplicationMenu(Menu, shell, options = {}) {
  const template = buildApplicationMenuTemplate(options);
  const repoUrl = options.repoUrl || REPO_URL;
  const wired = template.map((menu) => {
    if (menu.label !== "Help") return menu;
    return {
      ...menu,
      submenu: menu.submenu.map((item) =>
        item.url
          ? { label: item.label, click: () => { void shell.openExternal(item.url); } }
          : item,
      ),
    };
  });
  Menu.setApplicationMenu(Menu.buildFromTemplate(wired));
  return { template, repoUrl };
}

module.exports = { REPO_URL, buildApplicationMenuTemplate, applyApplicationMenu };
