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

module.exports = { contentSecurityPolicy, isApprovedExternalUrl, isSameOrigin, originOf };
