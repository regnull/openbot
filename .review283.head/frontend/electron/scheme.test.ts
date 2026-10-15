import { EventEmitter } from "node:events";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { APP_URL, createAppProtocolHandler, proxyApiRequest, routeAppRequest, schemePrivileges } from "./scheme.cjs";

const distDir = path.resolve("/bundle/dist");
const index = path.join(distDir, "index.html");
const built = new Set([index, path.join(distDir, "assets", "index-abc.js"), path.join(distDir, "logo-icon.svg")]);
const opts = { apiOrigin: "http://127.0.0.1:8000", distDir, fileExists: (p: string) => built.has(p) };

describe("app:// request routing", () => {
  it("registers a standard scheme so the packaged UI has a real origin", () => {
    expect(APP_URL).toBe("app://openbot/");
    expect(schemePrivileges[0]).toMatchObject({ scheme: "app", privileges: { standard: true, supportFetchAPI: true, stream: true } });
  });

  it("forwards API paths to the backend with their query string", () => {
    expect(routeAppRequest("app://openbot/api/v1/events?since=3", opts)).toEqual({ kind: "api", url: "http://127.0.0.1:8000/api/v1/events?since=3" });
  });

  it("serves built files from dist, including absolute /assets URLs", () => {
    expect(routeAppRequest("app://openbot/assets/index-abc.js", opts)).toEqual({ kind: "file", path: path.join(distDir, "assets", "index-abc.js") });
    expect(routeAppRequest("app://openbot/logo-icon.svg", opts)).toMatchObject({ kind: "file" });
  });

  it("falls back to index.html for the root and for client-side routes", () => {
    expect(routeAppRequest("app://openbot/", opts)).toEqual({ kind: "file", path: index });
    expect(routeAppRequest("app://openbot/threads/abc?x=1", opts)).toEqual({ kind: "file", path: index });
  });

  it("rejects paths that escape dist and foreign hosts", () => {
    // The URL parser collapses encoded dot segments before we see them, so this stays inside dist.
    expect(routeAppRequest("app://openbot/%2e%2e/%2e%2e/etc/passwd", opts)).toEqual({ kind: "file", path: index });
    // Encoded slashes survive parsing and only decode here, so this one must be caught by hand.
    expect(routeAppRequest("app://openbot/..%2f..%2fetc%2fpasswd", opts)).toEqual({ kind: "reject", status: 400 });
    expect(routeAppRequest("app://other/index.html", opts)).toEqual({ kind: "reject", status: 404 });
    expect(routeAppRequest("not a url", opts)).toEqual({ kind: "reject", status: 400 });
  });
});

/** A stand-in for Electron's net: records the ClientRequest calls and lets the test play the backend. */
function fakeNet() {
  const calls: any[] = [];
  const net = {
    fetch: vi.fn(async (url: string) => new Response(url)),
    request: vi.fn((options: any) => {
      const req: any = new EventEmitter();
      req.options = options; req.headers = {} as Record<string, string>; req.chunks = [] as Buffer[]; req.ended = false; req.aborted = false;
      req.setHeader = (k: string, v: string) => { req.headers[k] = v; };
      req.write = (c: Buffer) => req.chunks.push(c);
      req.end = () => { req.ended = true; };
      req.abort = () => { req.aborted = true; };
      req.respond = (status: number, headers: Record<string, string | string[]>) => { const incoming: any = new EventEmitter(); incoming.statusCode = status; incoming.statusMessage = "X"; incoming.headers = headers; incoming.resume = vi.fn(); req.emit("response", incoming); return incoming; };
      calls.push(req);
      return req;
    }),
  };
  return { net, calls };
}

const request = (init: { url: string; method?: string; headers?: Record<string, string>; body?: ReadableStream | null; signal?: AbortSignal }) =>
  ({ method: "GET", body: null, ...init, headers: new Headers(init.headers ?? {}) }) as unknown as Request;

describe("API proxy", () => {
  it("forwards method, headers and body, and skips hop-by-hop headers", async () => {
    const { net, calls } = fakeNet();
    const body = new Blob(['{"handle":"qa"}']).stream();
    const pending = proxyApiRequest(net, "http://127.0.0.1:8000/api/v1/bots", request({ url: "app://openbot/api/v1/bots", method: "POST", headers: { "x-api-key": "k", "content-type": "application/json", host: "openbot", "content-length": "15" }, body }));
    await vi.waitFor(() => expect(calls[0].ended).toBe(true));
    expect(calls[0].options).toMatchObject({ url: "http://127.0.0.1:8000/api/v1/bots", method: "POST" });
    expect(calls[0].headers).toEqual({ "x-api-key": "k", "content-type": "application/json" });
    expect(Buffer.concat(calls[0].chunks).toString()).toBe('{"handle":"qa"}');
    const incoming = calls[0].respond(201, { "content-type": "application/json", "transfer-encoding": "chunked" });
    const response = await pending;
    expect(response.status).toBe(201);
    expect(response.headers.get("content-type")).toBe("application/json");
    expect(response.headers.get("transfer-encoding")).toBeNull();
    incoming.emit("data", Buffer.from('{"id":'));
    incoming.emit("data", Buffer.from('"1"}'));
    incoming.emit("end");
    expect(await response.json()).toEqual({ id: "1" });
  });

  it("streams chunks as they arrive so server-sent events flow live", async () => {
    const { net, calls } = fakeNet();
    const pending = proxyApiRequest(net, "http://127.0.0.1:8000/api/v1/events", request({ url: "app://openbot/api/v1/events" }));
    await vi.waitFor(() => expect(calls[0].ended).toBe(true));
    const incoming = calls[0].respond(200, { "content-type": "text/event-stream" });
    const reader = (await pending).body!.getReader();
    incoming.emit("data", Buffer.from(": connected\n\n"));
    expect(new TextDecoder().decode((await reader.read()).value)).toBe(": connected\n\n");
    incoming.emit("data", Buffer.from("event: ping\n\n"));
    expect(new TextDecoder().decode((await reader.read()).value)).toBe("event: ping\n\n");
  });

  it("aborts the backend request when the renderer drops the response", async () => {
    const { net, calls } = fakeNet();
    const pending = proxyApiRequest(net, "http://127.0.0.1:8000/api/v1/events", request({ url: "app://openbot/api/v1/events" }));
    await vi.waitFor(() => expect(calls[0].ended).toBe(true));
    calls[0].respond(200, { "content-type": "text/event-stream" });
    const response = await pending;
    await response.body!.cancel();
    expect(calls[0].aborted).toBe(true);
  });

  it("aborts the backend request when the incoming request is aborted before a response", async () => {
    const { net, calls } = fakeNet();
    const ac = new AbortController();
    void proxyApiRequest(net, "http://127.0.0.1:8000/api/v1/bots", request({ url: "app://openbot/api/v1/bots", signal: ac.signal }));
    await vi.waitFor(() => expect(calls[0].ended).toBe(true));
    ac.abort();
    expect(calls[0].aborted).toBe(true);
  });

  it("returns a bodiless response for 204 and errors the stream if the backend drops", async () => {
    const { net, calls } = fakeNet();
    const noContent = proxyApiRequest(net, "http://127.0.0.1:8000/api/v1/bots/1", request({ url: "app://openbot/api/v1/bots/1", method: "DELETE" }));
    await vi.waitFor(() => expect(calls[0].ended).toBe(true));
    const incoming = calls[0].respond(204, {});
    expect((await noContent).body).toBeNull();
    expect(incoming.resume).toHaveBeenCalled();

    const dropped = proxyApiRequest(net, "http://127.0.0.1:8000/api/v1/events", request({ url: "app://openbot/api/v1/events" }));
    await vi.waitFor(() => expect(calls[1].ended).toBe(true));
    calls[1].respond(200, {}).emit("aborted");
    await expect((await dropped).text()).rejects.toThrow(/aborted/);
  });

  it("rejects when the backend is unreachable", async () => {
    const { net, calls } = fakeNet();
    const pending = proxyApiRequest(net, "http://127.0.0.1:8000/api/v1/health", request({ url: "app://openbot/api/v1/health" }));
    await vi.waitFor(() => expect(calls[0].ended).toBe(true));
    calls[0].emit("error", new Error("ECONNREFUSED"));
    await expect(pending).rejects.toThrow("ECONNREFUSED");
  });
});

describe("app:// protocol handler", () => {
  it("routes API requests to the proxy and dist files to file: URLs, rejecting bad paths", async () => {
    const { net, calls } = fakeNet();
    const handler = createAppProtocolHandler({ apiOrigin: "http://127.0.0.1:8000", distDir: path.resolve("dist"), net });
    void handler(request({ url: "app://openbot/api/v1/health" }));
    await vi.waitFor(() => expect(calls[0].options.url).toBe("http://127.0.0.1:8000/api/v1/health"));
    const doc = await handler(request({ url: "app://openbot/threads/1" }));
    expect(await doc.text()).toMatch(/^file:.*\/dist\/index\.html$/);
    const bad = await handler(request({ url: "app://openbot/..%2fpackage.json" }));
    expect(bad.status).toBe(400);
    expect(net.fetch).toHaveBeenCalledTimes(1);
  });
});
