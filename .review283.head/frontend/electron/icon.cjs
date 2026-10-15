const path = require("node:path");

// PNG rendered from public/logo-icon.svg: Electron can't load SVG window icons,
// and electron-builder derives the .icns/.ico from a >=512px PNG. Lives under
// electron/ so the packaged app ships it (electron-builder.yml `files`).
const appIconPath = path.join(__dirname, "assets", "icon.png");

module.exports = { appIconPath };
