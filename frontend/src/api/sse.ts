import { useEffect, useRef } from "react";
import { BASE, getApiKey } from "./client";
import type { BusEvent } from "./types";

const EVENTS = ["message.created", "run.updated", "run.event", "inbox.updated", "bots.updated", "waiters.updated", "thread.updated"];

/**
 * Open one bus subscription. Returns the unsubscribe function.
 *
 * `onReconnect` fires on every `onopen` *after* the first one. EventSource reconnects on its own,
 * but events published while the socket was down are never replayed, so a caller holding state
 * derived from those events has to refetch at that point or it silently drifts out of date.
 *
 * Framework-free (and with an injectable EventSource) so the first-open-is-not-a-reconnect rule is
 * testable without a DOM.
 */
export function subscribeBusEvents(
  url: string,
  onEvent: (e: BusEvent) => void,
  onReconnect?: () => void,
  open: (u: string) => EventSource = (u) => new EventSource(u),
): () => void {
  const es = open(url);
  let opened = false;
  es.onopen = () => {
    if (opened) onReconnect?.();
    opened = true;
  };
  const handler = (ev: MessageEvent) => { try { onEvent(JSON.parse(ev.data)); } catch { /* ignore */ } };
  EVENTS.forEach((n) => es.addEventListener(n, handler as EventListener));
  return () => es.close();
}

export function useBusEvents(
  threadId: string | null,
  onEvent: (e: BusEvent) => void,
  onReconnect?: () => void,
) {
  const cb = useRef(onEvent);
  const reconnected = useRef(onReconnect);
  useEffect(() => {
    cb.current = onEvent;
    reconnected.current = onReconnect;
  });
  useEffect(() => {
    const connect = () => {
      const params = new URLSearchParams();
      if (threadId) params.set("thread_id", threadId);
      const key = getApiKey();
      if (key) params.set("api_key", key);
      return subscribeBusEvents(`${BASE}/events?${params}`, (e) => cb.current(e), () => reconnected.current?.());
    };
    let close = connect();
    // Settings saves no longer reload the page; live subscriptions need the new credential too.
    const onKeyChanged = () => { close(); close = connect(); };
    window.addEventListener("openbot:api-key-changed", onKeyChanged);
    return () => { window.removeEventListener("openbot:api-key-changed", onKeyChanged); close(); };
  }, [threadId]);
}
