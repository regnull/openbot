// @vitest-environment jsdom
// Wiring tests: the API client must fire `openbot:backend-unavailable` exactly
// for the "backend not ready" class of failures (network TypeError, route-missing
// 404 after a restart, 5xx) and never for app-level errors (401/400, app 404s).
import { afterEach, describe, expect, it, vi } from "vitest";
import { Api } from "./client";
import { ApiError, backendUnavailableEvent } from "./errors";

const UNAUTHORIZED_EVENT = "openbot:unauthorized";

function listen() {
  const events: string[] = [];
  const handler = (e: Event) => events.push(e.type);
  window.addEventListener(backendUnavailableEvent, handler);
  window.addEventListener(UNAUTHORIZED_EVENT, handler);
  return {
    events,
    stop() {
      window.removeEventListener(backendUnavailableEvent, handler);
      window.removeEventListener(UNAUTHORIZED_EVENT, handler);
    },
  };
}

/** Minimal Response stand-in: client.ts only uses ok/status/statusText/text/json. */
function jsonResponse(status: number, body: unknown) {
  const text = body === "" ? "" : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "Status",
    text: async () => text,
    json: async () => body,
  };
}

let listener: ReturnType<typeof listen>;

afterEach(() => {
  vi.unstubAllGlobals();
  listener?.stop();
});

describe("api() backend-unavailable wiring", () => {
  it("dispatches on network failure (connection refused / backend down)", async () => {
    listener = listen();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(Api.listBots()).rejects.toBeInstanceOf(TypeError);
    expect(listener.events).toEqual([backendUnavailableEvent]);
  });

  it("dispatches on the restart case: 404 {\"detail\":\"Not Found\"}", async () => {
    listener = listen();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(404, { detail: "Not Found" })));
    await expect(Api.listBots()).rejects.toMatchObject({ status: 404 });
    expect(listener.events).toEqual([backendUnavailableEvent]);
  });

  it("dispatches on 5xx responses", async () => {
    listener = listen();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(502, { detail: "Bad Gateway" })));
    await expect(Api.listBots()).rejects.toBeInstanceOf(ApiError);
    expect(listener.events).toEqual([backendUnavailableEvent]);
  });

  it("does not dispatch on app-level 404s (deleted thread etc.)", async () => {
    listener = listen();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(404, { detail: "thread not found" })));
    await expect(Api.getThread("t1")).rejects.toMatchObject({ status: 404, message: '{"detail":"thread not found"}' });
    expect(listener.events).toEqual([]);
  });

  it("does not dispatch on 401 (fires openbot:unauthorized instead)", async () => {
    listener = listen();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, { detail: "unauthorized" })));
    await expect(Api.listBots()).rejects.toMatchObject({ status: 401 });
    expect(listener.events).toEqual([UNAUTHORIZED_EVENT]);
  });

  it("does not dispatch on 400", async () => {
    listener = listen();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(400, { detail: "bad request" })));
    await expect(Api.listBots()).rejects.toMatchObject({ status: 400 });
    expect(listener.events).toEqual([]);
  });

  it("does not dispatch on success", async () => {
    listener = listen();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, [{ id: "b1" }])));
    await expect(Api.listBots()).resolves.toEqual([{ id: "b1" }]);
    expect(listener.events).toEqual([]);
  });
});
