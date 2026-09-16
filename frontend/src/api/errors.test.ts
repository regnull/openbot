import { describe, expect, it } from "vitest";
import { ApiError, backendFallbackPath, backendFallbackPathFor, backendUnavailableEvent, isBackendUnavailable, isUnavailableStatus } from "./errors";

describe("isUnavailableStatus", () => {
  it("treats 404 and 5xx as backend unavailable", () => {
    expect(isUnavailableStatus(404)).toBe(true);
    expect(isUnavailableStatus(502)).toBe(true);
    expect(isUnavailableStatus(599)).toBe(true);
  });

  it("does not treat auth errors or client errors as unavailable", () => {
    expect(isUnavailableStatus(401)).toBe(false);
    expect(isUnavailableStatus(400)).toBe(false);
    expect(isUnavailableStatus(429)).toBe(false);
    expect(isUnavailableStatus(200)).toBe(false);
  });
});

describe("isBackendUnavailable", () => {
  it("matches the reported 404 {\"detail\":\"Not Found\"} case", () => {
    const err = new ApiError(404, '{"detail":"Not Found"}');
    expect(isBackendUnavailable(err)).toBe(true);
  });

  it("matches 5xx and network failures (fetch TypeErrors), not other errors", () => {
    expect(isBackendUnavailable(new ApiError(502, "Bad Gateway"))).toBe(true);
    expect(isBackendUnavailable(new TypeError("Failed to fetch"))).toBe(true);
    expect(isBackendUnavailable(new ApiError(401, "unauthorized"))).toBe(false);
    expect(isBackendUnavailable(new ApiError(400, "bad request"))).toBe(false);
    expect(isBackendUnavailable(new Error("boom"))).toBe(false);
    expect(isBackendUnavailable(null)).toBe(false);
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
