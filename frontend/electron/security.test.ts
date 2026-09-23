import { describe, expect, it } from "vitest";
import security from "./security.cjs";

describe("Electron security policy", () => {
  it("uses the resolved configured origin in CSP", () => {
    const csp = security.contentSecurityPolicy("https://desktop.example.test", "https://api.example.test");
    expect(csp).toContain("default-src 'self' https://desktop.example.test");
    expect(csp).toContain("connect-src 'self' https://desktop.example.test https://api.example.test");
    expect(csp).not.toContain("${configuredOrigin}");
  });

  it("allows the packaged default API origin for file renderers", () => {
    const csp = security.contentSecurityPolicy("null", "http://127.0.0.1:8000");
    expect(csp).toContain("connect-src 'self' null http://127.0.0.1:8000");
  });

  it("allows a remote OPENBOT_URL origin to serve API and SSE", () => {
    const csp = security.contentSecurityPolicy("https://openbot.example.test", "https://openbot.example.test");
    expect(csp).toContain("connect-src 'self' https://openbot.example.test");
  });

  it("approves OAuth authorization and LangSmith URLs only", () => {
    expect(security.isApprovedExternalUrl("https://login.example.test/authorize?client_id=x&redirect_uri=https%3A%2F%2Fapp.test&response_type=code&state=s")).toBe(true);
    expect(security.isApprovedExternalUrl("https://smith.langchain.com/o/-/projects/p/-/r/run")).toBe(true);
    expect(security.isApprovedExternalUrl("https://evil.example.test/phish")).toBe(false);
    expect(security.isApprovedExternalUrl("javascript:alert(1)")).toBe(false);
  });
});
