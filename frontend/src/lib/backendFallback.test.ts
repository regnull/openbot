import { describe, expect, it } from "vitest";
import { backendUnavailableMessage, isUnavailableErrorText } from "./backendFallback";

describe("isUnavailableErrorText", () => {
  it("detects the raw FastAPI 404 body from a restarted backend", () => {
    expect(isUnavailableErrorText('{"detail":"Not Found"}')).toBe(true);
  });

  it("detects plain-text 404/502 bodies", () => {
    expect(isUnavailableErrorText("Not Found")).toBe(true);
    expect(isUnavailableErrorText("502 Bad Gateway")).toBe(true);
    expect(isUnavailableErrorText("Internal Server Error")).toBe(true);
  });

  it("leaves real application errors alone", () => {
    expect(isUnavailableErrorText("Connection closed by peer mid-run")).toBe(false);
    expect(isUnavailableErrorText("Thread not found in the database")).toBe(false);
    expect(isUnavailableErrorText("")).toBe(false);
  });
});

describe("backendUnavailableMessage", () => {
  it("tells the user the backend is unreachable, not the raw response", () => {
    expect(backendUnavailableMessage).toBe(
      "Backend is unavailable — it may be restarting. Showing the default view; retry by reloading.",
    );
  });
});
