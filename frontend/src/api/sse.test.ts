import { describe, expect, it, vi } from "vitest";
import { subscribeBusEvents } from "./sse";

class FakeEventSource {
  onopen: (() => void) | null = null;
  listeners = new Map<string, EventListener>();
  closed = false;
  addEventListener(name: string, fn: EventListener) { this.listeners.set(name, fn); }
  close() { this.closed = true; }
  emit(name: string, data: unknown) { this.listeners.get(name)?.({ data: JSON.stringify(data) } as MessageEvent as Event); }
}

const subscribe = (onEvent = vi.fn(), onReconnect = vi.fn()) => {
  const es = new FakeEventSource();
  const stop = subscribeBusEvents("/events", onEvent, onReconnect, () => es as unknown as EventSource);
  return { es, stop, onEvent, onReconnect };
};

describe("subscribeBusEvents", () => {
  it("does not treat the first open as a reconnect", () => {
    const { es, onReconnect } = subscribe();
    es.onopen!();
    expect(onReconnect).not.toHaveBeenCalled();
  });

  it("fires onReconnect on every open after the first", () => {
    const { es, onReconnect } = subscribe();
    es.onopen!();
    es.onopen!();
    es.onopen!();
    expect(onReconnect).toHaveBeenCalledTimes(2);
  });

  it("works without an onReconnect callback", () => {
    const es = new FakeEventSource();
    subscribeBusEvents("/events", vi.fn(), undefined, () => es as unknown as EventSource);
    expect(() => { es.onopen!(); es.onopen!(); }).not.toThrow();
  });

  it("parses bus events and ignores malformed payloads", () => {
    const { es, onEvent } = subscribe();
    es.emit("run.updated", { event: "run.updated", data: { id: "r1" } });
    expect(onEvent).toHaveBeenCalledWith({ event: "run.updated", data: { id: "r1" } });
    es.listeners.get("run.updated")!({ data: "not json" } as MessageEvent as Event);
    expect(onEvent).toHaveBeenCalledTimes(1);
  });

  it("subscribes to bot updates for sidebar activity", () => {
    const { es, onEvent } = subscribe();
    es.emit("bots.updated", { event: "bots.updated", data: { id: "b1", active: true } });
    expect(onEvent).toHaveBeenCalledWith({ event: "bots.updated", data: { id: "b1", active: true } });
  });

  it("closes the stream on unsubscribe", () => {
    const { es, stop } = subscribe();
    stop();
    expect(es.closed).toBe(true);
  });
});
