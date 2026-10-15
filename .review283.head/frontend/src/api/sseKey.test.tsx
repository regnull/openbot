// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { setApiKey } from "./client";
import { useBusEvents } from "./sse";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("reconnects live subscriptions after an API key save, but not failed persistence", async () => {
  const streams: FakeEventSource[] = [];
  class FakeEventSource {
    url: string;
    addEventListener = vi.fn();
    close = vi.fn();
    constructor(url: string) { this.url = url; streams.push(this); }
  }
  vi.stubGlobal("EventSource", FakeEventSource);
  localStorage.clear();
  const el = document.createElement("div");
  const root = createRoot(el);
  function Probe() { useBusEvents(null, () => {}); return null; }
  try {
    await act(async () => root.render(<Probe />));
    setApiKey("secret");
    expect(streams).toHaveLength(2);
    expect(streams[0].close).toHaveBeenCalledOnce();
    expect(streams[1].url).toContain("api_key=secret");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(() => setApiKey("other")).toThrow("blocked");
    expect(streams).toHaveLength(2);
    setApiKey("");
    expect(streams).toHaveLength(3);
    expect(streams[2].url).not.toContain("api_key");
  } finally {
    await act(async () => root.unmount());
    expect(streams.at(-1)?.close).toHaveBeenCalledOnce();
    vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear();
  }
});
