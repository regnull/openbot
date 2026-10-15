from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from openbot.api.deps import get_services
from openbot.runtime.bus import CLOSED, EventBus
from openbot.services import Services

router = APIRouter(prefix="/events", tags=["events"])


async def event_stream(bus: EventBus, thread_id: str | None) -> AsyncIterator[str]:
    async with bus.subscribe(thread_id) as q:
        yield ": connected\n\n"
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=15)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if item is CLOSED:
                return          # server shutting down: end the response so the connection can drain
            yield f"event: {item['event']}\ndata: {json.dumps(item, default=str)}\n\n"


@router.get("")
async def events(thread_id: str | None = None, services: Services = Depends(get_services)) -> StreamingResponse:
    return StreamingResponse(
        event_stream(services.bus, thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
