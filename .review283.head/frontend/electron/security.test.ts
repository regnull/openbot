import { describe, expect, it } from "vitest";
import security from "./security.cjs";

describe("Electron security policy", () => {
  it("uses the resolved configured origin in CSP", () => {
    const csp = security.contentSecurityPolicy("https://desktop.example.test", "https://api.example.test");
    expect(csp).toContain("default-src 'self' https://desktop.example.test");
    expect(csp).toContain("connect-src 'self' https://desktop.example.test https://api.example.test");
    expect(csp).not.toContain("${configuredOrigin}");
  });

  it("names the packaged app origin, never the opaque \"null\" origin", () => {
    const csp = security.contentSecurityPolicy(security.originOf("app://openbot/"), "http://127.0.0.1:8000");
    expect(csp).toContain("default-src 'self' app://openbot");
    expect(csp).not.toContain("null");
  });

  it("allows a remote OPENBOT_URL origin to serve API and SSE", () => {
    const csp = security.contentSecurityPolicy("https://openbot.example.test", "https://openbot.example.test");
    expect(csp).toContain("connect-src 'self' https://openbot.example.test");
  });

  it("treats the packaged app scheme as one real origin", () => {
    expect(security.originOf("app://openbot/threads/1?x=1#y")).toBe("app://openbot");
    expect(security.isSameOrigin("app://openbot/threads/1", "app://openbot/")).toBe(true);
    expect(security.isSameOrigin("app://other/", "app://openbot/")).toBe(false);
    expect(security.isSameOrigin("file:///etc/passwd", "app://openbot/")).toBe(false);
  });

  it("never treats opaque origins as same-origin, even with each other", () => {
    expect(security.isSameOrigin("file:///a/index.html", "file:///a/index.html")).toBe(false);
    expect(security.isSameOrigin("not a url", "app://openbot/")).toBe(false);
  });

  it("preserves origin comparison for HTTP deployments", () => {
    expect(security.isSameOrigin("https://openbot.example.test/inbox", "https://openbot.example.test")).toBe(true);
    expect(security.isSameOrigin("https://evil.example.test", "https://openbot.example.test")).toBe(false);
  });

  it("approves OAuth authorization and LangSmith URLs only", () => {
    expect(security.isApprovedExternalUrl("https://login.example.test/authorize?client_id=x&redirect_uri=https%3A%2F%2Fapp.test&response_type=code&state=s")).toBe(true);
    expect(security.isApprovedExternalUrl("https://smith.langchain.com/o/-/projects/p/-/r/run")).toBe(true);
    expect(security.isApprovedExternalUrl("https://evil.example.test/phish")).toBe(false);
    expect(security.isApprovedExternalUrl("javascript:alert(1)")).toBe(false);
  });
});
