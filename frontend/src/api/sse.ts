import { useEffect, useRef } from "react";
import { BASE, getApiKey } from "./client";
import type { BusEvent } from "./types";

const EVENTS = ["message.created", "run.updated", "run.event", "inbox.updated"];

export function useBusEvents(threadId: string | null, onEvent: (e: BusEvent) => void) {
  const cb = useRef(onEvent);
  useEffect(() => {
    cb.current = onEvent;
  });
  useEffect(() => {
    const params = new URLSearchParams();
    if (threadId) params.set("thread_id", threadId);
    const key = getApiKey();
    if (key) params.set("api_key", key);
    const es = new EventSource(`${BASE}/events?${params}`);
    const handler = (ev: MessageEvent) => { try { cb.current(JSON.parse(ev.data)); } catch { /* ignore */ } };
    EVENTS.forEach((n) => es.addEventListener(n, handler as EventListener));
    return () => es.close();
  }, [threadId]);
}
