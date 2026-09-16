import { describe, expect, it } from "vitest";
import { ApiError, backendFallbackPath, backendFallbackPathFor, backendUnavailableEvent, isBackendUnavailable, isUnavailableStatus } from "./errors";

describe("isUnavailableStatus", () => {
  it("treats 5xx as backend unavailable regardless of body", () => {
    expect(isUnavailableStatus(502, "Bad Gateway")).toBe(true);
    expect(isUnavailableStatus(599, "anything")).toBe(true);
    expect(isUnavailableStatus(500, "thread not found")).toBe(true);
  });

  it("treats a route-missing 404 (the restart case) as unavailable", () => {
    expect(isUnavailableStatus(404, '{"detail":"Not Found"}')).toBe(true);
    expect(isUnavailableStatus(404, '{"detail":"not found"}')).toBe(true);
    expect(isUnavailableStatus(404, "")).toBe(true); // empty body: proxies drop it
    expect(isUnavailableStatus(404, "<html>502 Bad Gateway</html>")).toBe(true);
    expect(isUnavailableStatus(404, "<html>503 Service Temporarily Unavailable</html>")).toBe(true);
  });

  it("does not treat app-level 404s as unavailable", () => {
    for (const body of [
      '{"detail":"thread not found"}',
      '{"detail":"bot not found"}',
      '{"detail":"run not found"}',
      '{"detail":"item not found"}',
      '{"detail":"actor not found"}',
    ]) {
      expect(isUnavailableStatus(404, body), body).toBe(false);
    }
  });

  it("does not treat auth errors or client errors as unavailable", () => {
    expect(isUnavailableStatus(401, "unauthorized")).toBe(false);
    expect(isUnavailableStatus(400, "bad request")).toBe(false);
    expect(isUnavailableStatus(429, "rate limited")).toBe(false);
    expect(isUnavailableStatus(200, "")).toBe(false);
  });
});

describe("isBackendUnavailable", () => {
  it("matches the reported 404 {\"detail\":\"Not Found\"} case", () => {
    const err = new ApiError(404, '{"detail":"Not Found"}');
    expect(isBackendUnavailable(err)).toBe(true);
  });

  it("matches 5xx, route-missing 404s and network failures (fetch TypeErrors)", () => {
    expect(isBackendUnavailable(new ApiError(502, "Bad Gateway"))).toBe(true);
    expect(isBackendUnavailable(new ApiError(404, '{"detail":"Not Found"}'))).toBe(true);
    expect(isBackendUnavailable(new TypeError("Failed to fetch"))).toBe(true);
    expect(isBackendUnavailable(new ApiError(401, "unauthorized"))).toBe(false);
    expect(isBackendUnavailable(new ApiError(400, "bad request"))).toBe(false);
    expect(isBackendUnavailable(new Error("boom"))).toBe(false);
    expect(isBackendUnavailable(null)).toBe(false);
  });

  it("does not swallow app-level 404s (deleted thread from a stale link, etc.)", () => {
    expect(isBackendUnavailable(new ApiError(404, '{"detail":"thread not found"}'))).toBe(false);
    expect(isBackendUnavailable(new ApiError(404, '{"detail":"run not found"}'))).toBe(false);
    expect(isBackendUnavailable(new ApiError(404, '{"detail":"bot not found"}'))).toBe(false);
  });

  it("home fallback target has a loop guard", () => {
    expect(backendFallbackPath).toBe("/inbox");
    expect(backendFallbackPathFor("/threads/abc")).toBe("/inbox");
    expect(backendFallbackPathFor("/inbox")).toBe(null); // already home: no redirect loop
  });

  it("event name constant", () => {
    expect(backendUnavailableEvent).toBe("openbot:backend-unavailable");
  });
});
