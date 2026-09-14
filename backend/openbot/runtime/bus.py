from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class EventBus:
    def __init__(self, maxsize: int = 1000) -> None:
        self._subs: dict[asyncio.Queue, str | None] = {}
        self._maxsize = maxsize

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
        try:
            yield q
        finally:
            self._subs.pop(q, None)
