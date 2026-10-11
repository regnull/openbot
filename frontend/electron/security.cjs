const LANGSMITH_HOSTS = new Set(["smith.langchain.com", "www.smith.langchain.com"]);

function isApprovedExternalUrl(rawUrl) {
  let url;
  try { url = new URL(rawUrl); } catch { return false; }
  if (url.protocol !== "https:") return false;
  if (LANGSMITH_HOSTS.has(url.hostname)) return true;
  // OAuth authorization endpoints are identified by the standard authorization
  // request parameters. This keeps arbitrary external navigation blocked while
  // allowing providers whose host is configured by an MCP server.
  return url.searchParams.has("client_id") &&
    url.searchParams.has("redirect_uri") &&
    url.searchParams.has("response_type") &&
    url.searchParams.has("state");
}

/**
 * A link the app asks to open in a new window (a link in a message, a model's source page) goes to
 * the system browser, but only on the web. shell.openExternal hands any scheme to the OS, which
 * would also open file: and smb: URLs or launch custom app-protocol handlers.
 */
function isWebUrl(rawUrl) {
  let url;
  try { url = new URL(rawUrl); } catch { return false; }
  return url.protocol === "https:" || url.protocol === "http:";
}

/**
 * Origin of a URL as Chromium sees it. Node's URL parser gives non-special schemes such as
 * app://openbot the opaque origin "null", but a scheme registered as standard is a real origin
 * in the renderer, so rebuild it from scheme and host.
 */
function originOf(rawUrl) {
  const url = new URL(rawUrl);
  if (url.origin !== "null") return url.origin;
  return url.host ? `${url.protocol}//${url.host}` : "null";
}

function isSameOrigin(rawUrl, configuredUrl) {
  try {
    const candidate = originOf(rawUrl);
    // Opaque origins (file://, data:) are never same-origin with anything, including each other.
    return candidate !== "null" && candidate === originOf(configuredUrl);
  } catch {
    return false;
  }
}

function contentSecurityPolicy(configuredOrigin, apiOrigin = configuredOrigin) {
  return [
    `default-src 'self' ${configuredOrigin}`,
    "img-src 'self' data: blob:",
    "style-src 'self' 'unsafe-inline'",
    "script-src 'self' 'unsafe-inline'",
    `connect-src 'self' ${configuredOrigin} ${apiOrigin}`,
  ].join("; ");
}

module.exports = { contentSecurityPolicy, isApprovedExternalUrl, isSameOrigin, isWebUrl, originOf };
