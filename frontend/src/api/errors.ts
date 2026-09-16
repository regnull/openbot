export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

/**
 * True when a response status means "backend not ready to serve this request":
 * 404 (route missing after a restart / stale proxy) or any 5xx (crashed or
 * starting up). Auth failures (401), rate limits (429) and client mistakes
 * (400-499 generally) are deliberately excluded — those need different UI.
 */
export function isUnavailableStatus(status: number): boolean {
  return status === 404 || (status >= 500 && status <= 599);
}

/**
 * True when a failure looks like the backend being down or restarting
 * (404 `{"detail":"Not Found"}`, connection refused, 5xx) rather than an
 * application-level error the user should read. `fetch` reports network
 * failures as a TypeError instead of a response.
 */
export function isBackendUnavailable(error: unknown): boolean {
  if (error instanceof ApiError) return isUnavailableStatus(error.status);
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
