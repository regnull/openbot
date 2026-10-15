from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

CLOSED = None   # sentinel a subscriber receives when the bus shuts down


class EventBus:
    def __init__(self, maxsize: int = 1000) -> None:
        self._subs: dict[asyncio.Queue, str | None] = {}
        self._maxsize = maxsize
        self.closed = False

    def close(self) -> None:
        """End every subscriber's stream and turn away new ones.

        Called from uvicorn's exit hook on the first shutdown signal. uvicorn waits for open
        connections to drain before it runs the lifespan shutdown, and a browser's event stream never
        closes by itself, so without this Ctrl+C hung until a second Ctrl+C force-cancelled the
        connections (logged as "Exception in ASGI application"). Safe to call more than once and from a
        signal handler: it only touches queues, which asyncio hands off to the loop.
        """
        self.closed = True
        for q in list(self._subs):
            self._offer(q, CLOSED)

    async def publish(self, event: str, thread_id: str | None, data: dict) -> None:
        item = {"event": event, "thread_id": thread_id, "data": data}
        for q, filt in list(self._subs.items()):
            if filt is not None and filt != thread_id:
                continue
            if q.full():
                self._drop_oldest(q)
                self._offer(q, {"event": "overflow", "thread_id": thread_id, "data": {"dropped": 1}})
            self._offer(q, item)

    @staticmethod
    def _drop_oldest(q: asyncio.Queue) -> None:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass

    @classmethod
    def _offer(cls, q: asyncio.Queue, item: dict) -> None:
        if q.full():
            cls._drop_oldest(q)
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            pass

    @asynccontextmanager
    async def subscribe(self, thread_id: str | None) -> AsyncIterator[asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subs[q] = thread_id
        if self.closed:
            self._offer(q, CLOSED)
        try:
            yield q
        finally:
            self._subs.pop(q, None)
