/**
 * Copy and text-level detection for "the backend is down or restarting".
 *
 * Two layers of defense:
 *  1. The API client fires `openbot:backend-unavailable` and BackendFallback
 *     navigates to the home view before errors reach the screen (see
 *     src/api/errors.ts and src/components/BackendFallback.tsx).
 *  2. If an error string still reaches a page (e.g. it raced the navigation,
 *     or was captured before the event fired), ErrorText recognizes the
 *     "unavailable" class of raw responses and swaps in friendly copy.
 */
export const backendUnavailableMessage =
  "Backend is unavailable — it may be restarting. Showing the default view; retry by reloading.";

/**
 * Best-effort recognition of raw backend responses that reached the UI as
 * text: FastAPI's 404 body, nginx-style plain-text 404/50x bodies. These
 * strings are machine-generated, not user input, so this is safe matching,
 * and worst case the user sees the raw text as before.
 */
export function isUnavailableErrorText(text: string): boolean {
  const t = (text ?? "").trim().toLowerCase();
  if (!t) return false;
  if (t.includes('"detail":"not found"')) return true; // FastAPI/Starlette 404 body
  if (t === "not found") return true;
  if (t.startsWith("50") && t.includes("bad gateway")) return true;
  if (t.includes("internal server error")) return true;
  return false;
}
