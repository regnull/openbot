export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

/**
 * Bodies that mean "no such route / proxy can't reach the backend" rather than
 * "the app looked for a resource and didn't find it": FastAPI's default
 * {"detail":"Not Found"} (what a freshly restarted backend answers for any
 * unknown path), an empty body (some proxies), or a proxy/gateway error page.
 */
const routeMissing404 = new Set([
  "not found",
  '{"detail":"not found"}',
]);

function isRouteMissingBody(message: string): boolean {
  const normalized = message.trim().toLowerCase();
  if (normalized === "") return true; // empty body: proxies often drop it
  if (routeMissing404.has(normalized)) return true;
  // Proxy error pages: "502 Bad Gateway", "503 Service Temporarily Unavailable", nginx default html, ...
  return /\b(bad gateway|service (?:temporarily )?unavailable|gateway time-?out|proxy|nginx|varnish|cloudflare)\b/.test(normalized);
}

/**
 * True when a response status means "backend not ready to serve this request":
 * any 5xx (crashed or starting up), or a 404 whose body says the route itself
 * is missing (`{"detail":"Not Found"}` after a restart / stale proxy) rather
 * than an application-level 404 ({"detail":"thread not found"} etc.), which
 * must render as a normal error. Auth failures (401), rate limits (429) and
 * client mistakes (400-499 generally) are deliberately excluded.
 */
export function isUnavailableStatus(status: number, message: string): boolean {
  if (status >= 500 && status <= 599) return true;
  if (status === 404) return isRouteMissingBody(message);
  return false;
}

/**
 * True when a failure looks like the backend being down or restarting
 * (404 `{"detail":"Not Found"}`, connection refused, 5xx) rather than an
 * application-level error the user should read. `fetch` reports network
 * failures as a TypeError instead of a response.
 */
export function isBackendUnavailable(error: unknown): boolean {
  if (error instanceof ApiError) return isUnavailableStatus(error.status, error.message);
  // Network-level failures: fetch rejects with TypeError ("Failed to fetch", "load failed").
  return error instanceof TypeError;
}

/** Where "go home" lands: the default view is the inbox. */
export const backendFallbackPath = "/inbox";

/**
 * Path to navigate to when the backend is unavailable, with a loop guard:
 * if the user is already on the fallback view, return null so callers don't
 * re-trigger navigation (the home view's own failing queries then just show
 * the friendly offline copy until the backend is back).
 */
export function backendFallbackPathFor(currentPath: string | null): string | null {
  if (currentPath === backendFallbackPath) return null;
  return backendFallbackPath;
}

/** Fired (from client.ts) whenever a request fails with a backend-unavailable error. */
export const backendUnavailableEvent = "openbot:backend-unavailable";
