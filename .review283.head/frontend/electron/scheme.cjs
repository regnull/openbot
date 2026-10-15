const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

// The packaged app is served from this privileged scheme rather than from file://. A file:// page
// has the opaque origin "null": Vite's absolute /assets URLs resolve to the filesystem root,
// BrowserRouter sees the on-disk path instead of a route, and every API call is cross-origin --
// which the backend could only accept by allowlisting the "null" origin, one any web page can
// produce from a sandboxed iframe. app://openbot is a real origin. The handler below serves the
// Vite build from dist/ and forwards /api/* to the backend, so the renderer runs the same
// same-origin build the browser and the Vite dev proxy already run.
const APP_SCHEME = "app";
const APP_HOST = "openbot";
const APP_URL = `${APP_SCHEME}://${APP_HOST}/`;
const API_PREFIX = "/api/";

// Must be registered before app "ready"; `standard` is what gives the scheme a real origin.
const schemePrivileges = [{ scheme: APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } }];

const NULL_BODY_STATUSES = new Set([101, 204, 205, 304]);
// Hop-by-hop and connection-level headers belong to each leg of the proxy, not to the payload.
const SKIPPED_REQUEST_HEADERS = new Set(["host", "connection", "content-length", "transfer-encoding", "keep-alive", "upgrade"]);
const SKIPPED_RESPONSE_HEADERS = new Set(["connection", "content-length", "transfer-encoding", "keep-alive", "upgrade", "content-encoding"]);

function isExistingFile(candidate) {
  try { return fs.statSync(candidate).isFile(); } catch { return false; }
}

/** Map an app:// request to a backend URL, a file under distDir, or a rejection status. */
function routeAppRequest(rawUrl, { apiOrigin, distDir, fileExists = isExistingFile }) {
  let url;
  try { url = new URL(rawUrl); } catch { return { kind: "reject", status: 400 }; }
  if (url.protocol !== `${APP_SCHEME}:` || url.host !== APP_HOST) return { kind: "reject", status: 404 };
  if (url.pathname.startsWith(API_PREFIX)) return { kind: "api", url: `${apiOrigin}${url.pathname}${url.search}` };
  let pathname;
  try { pathname = decodeURIComponent(url.pathname); } catch { return { kind: "reject", status: 400 }; }
  const resolved = path.resolve(distDir, `.${pathname}`);
  const relative = path.relative(distDir, resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) return { kind: "reject", status: 400 };
  // Client-side routes (/threads/<id>) and anything else that is not a built file get index.html,
  // as the Vite dev server and the backend's SPA fallback do.
  return { kind: "file", path: fileExists(resolved) ? resolved : path.join(distDir, "index.html") };
}

/**
 * Forward one API request to the backend with Electron's net.request and stream the reply back.
 *
 * Not net.fetch: its response body cannot be cancelled once headers have arrived, so every
 * EventSource the renderer closes (reconnects, reloads, navigation) would leave its backend
 * connection open in the main process. Chromium allows six sockets per host, after which every
 * API call hangs. Here the body stream's `cancel` -- which Electron invokes when the renderer
 * drops the request -- aborts the upstream request instead.
 */
async function proxyApiRequest(net, url, request) {
  const upstream = net.request({ url, method: request.method, redirect: "manual" });
  for (const [name, value] of request.headers) {
    if (!SKIPPED_REQUEST_HEADERS.has(name.toLowerCase())) upstream.setHeader(name, value);
  }
  request.signal?.addEventListener("abort", () => upstream.abort(), { once: true });
  const response = new Promise((resolve, reject) => {
    upstream.on("error", reject);
    upstream.on("response", (incoming) => resolve(toResponse(incoming, upstream, request.method)));
  });
  if (request.body) {
    try {
      for await (const chunk of request.body) upstream.write(Buffer.from(chunk));
    } catch (error) {
      upstream.abort();
      throw error;
    }
  }
  upstream.end();
  return response;
}

function toResponse(incoming, upstream, method) {
  const headers = new Headers();
  for (const [name, value] of Object.entries(incoming.headers)) {
    if (SKIPPED_RESPONSE_HEADERS.has(name.toLowerCase())) continue;
    for (const v of Array.isArray(value) ? value : [value]) headers.append(name, v);
  }
  const noBody = method === "HEAD" || NULL_BODY_STATUSES.has(incoming.statusCode);
  let settled = false;
  const body = noBody ? null : new ReadableStream({
    start(controller) {
      const finish = (fn) => { if (!settled) { settled = true; fn(); } };
      incoming.on("data", (chunk) => { if (!settled) controller.enqueue(new Uint8Array(chunk)); });
      incoming.on("end", () => finish(() => controller.close()));
      incoming.on("error", (error) => finish(() => controller.error(error)));
      incoming.on("aborted", () => finish(() => controller.error(new Error("backend connection aborted"))));
    },
    cancel() { settled = true; upstream.abort(); },
  });
  if (noBody) incoming.resume();
  return new Response(body, { status: incoming.statusCode, statusText: incoming.statusMessage, headers });
}

/**
 * Build the protocol.handle callback. `net` is Electron's net module, injected so the handler can
 * be exercised without Electron. Static files come from dist via net.fetch on a file: URL; the
 * session.webRequest hook in main.cjs sees these responses and attaches the CSP header.
 */
function createAppProtocolHandler({ apiOrigin, distDir, net }) {
  return (request) => {
    const route = routeAppRequest(request.url, { apiOrigin, distDir });
    if (route.kind === "reject") return new Response(null, { status: route.status });
    if (route.kind === "api") return proxyApiRequest(net, route.url, request);
    return net.fetch(pathToFileURL(route.path).toString());
  };
}

module.exports = { APP_SCHEME, APP_HOST, APP_URL, schemePrivileges, routeAppRequest, proxyApiRequest, createAppProtocolHandler };
