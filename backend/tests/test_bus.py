import asyncio
import json

from fastapi.responses import StreamingResponse

from openbot.api.events import event_stream, events
from openbot.runtime.bus import EventBus


async def test_publish_filters_by_thread():
    bus = EventBus()
    async with bus.subscribe("t1") as q1, bus.subscribe(None) as qall:
        await bus.publish("message.created", "t1", {"x": 1})
        await bus.publish("message.created", "t2", {"x": 2})
        assert (await q1.get())["data"] == {"x": 1}
        assert q1.empty()
        assert (await qall.get())["data"] == {"x": 1}
        assert (await qall.get())["data"] == {"x": 2}


async def test_overflow_drops_oldest():
    bus = EventBus(maxsize=2)
    async with bus.subscribe(None) as q:
        for i in range(4):
            await bus.publish("e", None, {"i": i})
        items = [q.get_nowait() for _ in range(q.qsize())]
        assert items[-1]["data"] == {"i": 3}
        assert any(it["event"] == "overflow" for it in items)


async def test_event_stream_frames():
    bus = EventBus()
    gen = event_stream(bus, "t1")
    connected = await asyncio.wait_for(gen.__anext__(), timeout=1)
    assert connected == ": connected\n\n"

    await bus.publish("message.created", "t1", {"hello": "world"})
    await bus.publish("message.created", "t2", {"should": "not appear"})

    frame = None
    while True:
        frame = await asyncio.wait_for(gen.__anext__(), timeout=1)
        if "\ndata:" in frame:
            break

    lines = frame.split("\n")
    assert any(line == "event: message.created" for line in lines)
    data_line = next(line for line in lines if line.startswith("data:"))
    payload = json.loads(data_line[len("data:"):].strip())
    assert set(payload.keys()) == {"event", "thread_id", "data"}
    assert payload["data"] == {"hello": "world"}

    await gen.aclose()


async def test_events_route_is_sse(services):
    resp = await events(thread_id=None, services=services)
    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "text/event-stream"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    await resp.body_iterator.aclose()
