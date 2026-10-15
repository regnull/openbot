/**
 * Parse `--backend_url <url>` from an argv array (default: process.argv).
 *
 * Supports both `--backend_url <url>` (space-separated) and `--backend_url=<url>`
 * forms.  Returns the URL string with any trailing slashes stripped, or null when
 * the flag is absent.
 */
function parseBackendUrl(argv = process.argv) {
  for (let i = 2; i < argv.length; i++) { // start at 2 to skip the executable and possibly an Electron flag
    const arg = argv[i];
    if (arg === "--backend_url" && i + 1 < argv.length) {
      return argv[i + 1].replace(/\/+$/, "");
    }
    const eqMatch = arg.match(/^--backend_url=(.+)$/);
    if (eqMatch) {
      return eqMatch[1].replace(/\/+$/, "");
    }
  }
  return null;
}

function resolveApiOrigin(env = process.env, backendUrl = parseBackendUrl()) {
  if (backendUrl) return backendUrl;
  if (env.OPENBOT_API_URL) return env.OPENBOT_API_URL;
  if (env.OPENBOT_URL?.startsWith("http")) return new URL(env.OPENBOT_URL).origin;
  return `http://127.0.0.1:${env.OPENBOT_BACKEND_PORT || "8000"}`;
}

module.exports = { parseBackendUrl, resolveApiOrigin };
