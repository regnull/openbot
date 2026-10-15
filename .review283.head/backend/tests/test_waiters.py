"""The thread window's waiting state: a bot with queued, unpicked mail in a thread.

The transitions the UI cares about (AC): mention delivered -> bot busy -> "waiting" shown -> bot picks
the items up (a run starts) -> indicator cleared. The state is never stored; every assertion here goes
through `waiters_for` (what GET /threads/{id} serves) and/or the `waiters.updated` bus events (what
the SSE stream delivers), i.e. exactly what the thread window sees.
"""
import asyncio

from sqlalchemy import select

from openbot.db.models import Actor, InboxItem, Run
from openbot.runtime.delivery import create_thread, human_actor
from openbot.runtime.waiters import refresh_waiters_at_start, waiters_for
from tests.conftest import build_test_services
from tests.factories import bot_actor, external_actor
from tests.fakes import ScriptedChatModel, ai
from tests.test_actor_system import post, setup, until


def labels(waiters):
    """(handle, position, queue_len) per waiter, so assertions read like the UI line does."""
    return [(w.handle, w.position, w.queue_len) for w in waiters]


async def waiters(services, thread_id):
    async with services.session_factory() as s:
        return await waiters_for(s, thread_id)


async def collect(bus, thread_id, out):
    """Record every bus event for one thread (what an SSE subscriber would receive)."""
    async with bus.subscribe(thread_id) as q:
        while True:
            out.append(await q.get())


def waiter_events(events):
    return [e for e in events if e["event"] == "waiters.updated"]


async def running_run(services):
    async with services.session_factory() as s:
        rs = (await s.execute(select(Run).where(Run.status == "running"))).scalars().all()
    return rs[0] if rs else None


class Slow:
    """A model call slow enough that a bot is observably busy in one thread while mail queues up."""

    def __iter__(self):
        return self

    def __next__(self):
        import time
        time.sleep(1.0)
        from langchain_core.messages import AIMessage
        return AIMessage(content="late")


async def test_delivered_busy_cleared(settings):
    """The full event transition: delivered -> waiting shown -> bot picks up -> cleared."""
    ScriptedChatModel.seen.clear()
    services, t = await setup(settings, {"eng": [ai("one")]})
    events: list[dict] = []
    listener = asyncio.create_task(collect(services.bus, t.id, events))
    try:
        # notify() runs after the delivery publish, so the worker cannot pick the items up before
        # the "waiting" event exists: the order here is deterministic, not a race.
        await post(services, t, "hi")
        await services.actors.wait_idle()
        ws_events = waiter_events(events)
        shown = [w["data"]["waiters"] for w in ws_events if w["data"]["waiters"]]
        assert [(ws[0]["handle"], ws[0]["position"], ws[0]["queue_len"]) for ws in shown] \
            == [("eng", 1, 1)]
        # The bot picked the items up: the last event the window saw said "nobody waiting".
        assert ws_events[-1]["data"] == {"waiters": []}
        assert await waiters(services, t.id) == []
    finally:
        listener.cancel()


async def test_busy_bot_shows_waiting(settings):
    """A bot running another thread shows here as waiting; cancelling the run clears it."""
    ScriptedChatModel.seen.clear()
    services, t1 = await setup(settings, {}, handles=("eng",))
    services.model_factory = lambda actor: ScriptedChatModel(messages=Slow())
    async with services.session_factory() as s:
        you = await human_actor(s)
        t2 = await create_thread(services, s, title="second", handles=["eng"], created_by=you)
    await post(services, t1, "go")
    run = await until(lambda: running_run(services), timeout=2.0)
    await post(services, t2, "@eng now me")
    ws = await waiters(services, t2.id)
    assert labels(ws) == [("eng", 1, 1)]      # t1's items are "processing", not queued
    assert await waiters(services, t1.id) == []   # the thread being served shows no waiter
    await services.actors.cancel_run(run.id)
    await services.actors.wait_idle()
    assert await waiters(services, t2.id) == []   # picked up: t2's items are next in the FIFO


async def test_queue_position_spans_threads(settings):
    """A bot's inbox is one FIFO across threads, so the position shown in this thread counts mail
    queued in other threads too (that is the honest number while the bot is busy elsewhere)."""
    services = await build_test_services(settings, {"eng": [ai("one")]})
    try:
        async with services.session_factory() as s:
            s.add_all([bot_actor("eng")])
            await s.commit()
            you = await human_actor(s)
            t1 = await create_thread(services, s, title="one", handles=["eng"], created_by=you)
            t2 = await create_thread(services, s, title="two", handles=["eng"], created_by=you)
        # No actor system running: both deliveries stay queued, exactly the "bot is busy" state.
        await post(services, t1, "first")
        await post(services, t2, "second")
        assert labels(await waiters(services, t1.id)) == [("eng", 1, 2)]
        assert labels(await waiters(services, t2.id)) == [("eng", 2, 2)]
    finally:
        if services.http_client:
            await services.http_client.aclose()


async def test_only_bots_wait(settings):
    """External actors answer over webhooks and the human's queued mail is unread mail: neither is a
    busy-bot signal, so neither shows in the thread window."""
    services, t = await setup(settings, {}, handles=("eng", "ext2"))
    services.model_factory = lambda actor: ScriptedChatModel(messages=iter([ai("ok")]))
    # Turn @ext2 into an external actor (Actor.kind decides visibility, not the handle). The profile
    # is what the ExternalActor worker reads; without a webhook it simply has nothing to pick up.
    async with services.session_factory() as s:
        ext = (await s.execute(select(Actor).where(Actor.handle == "ext2"))).scalar_one()
        ext.kind = "external"
        ext.external = external_actor("x").external
        ext.external.webhook_url = None
        await s.commit()
    # The human's own queued mail in this thread must not show either.
    async with services.session_factory() as s:
        you = await human_actor(s)
        s.add(InboxItem(actor_id=you.id, thread_id=t.id, kind="message", payload={}))
        await s.commit()
    await post(services, t, "@eng ping")
    await services.actors.wait_idle()
    assert await waiters(services, t.id) == []


async def test_waiters_survive_a_restart(settings):
    """After a restart the items are queued again with nobody re-delivering, so start() re-broadcasts
    the waiting state (a listener that connects after the facts must not miss it)."""
    services, t = await setup(settings, {}, handles=("eng",))
    services.model_factory = lambda actor: ScriptedChatModel(messages=_Die())
    await post(services, t, "go")
    await services.actors.wait_idle()
    async with services.session_factory() as s:
        its = (await s.execute(select(InboxItem).where(InboxItem.kind == "message"))).scalars().all()
        assert its
        for it in its:
            it.status = "queued"      # what recovery on start() does to orphaned "processing" items
        await s.commit()
    assert labels(await waiters(services, t.id)) == [("eng", 1, 1)]
    events: list[dict] = []
    listener = asyncio.create_task(collect(services.bus, t.id, events))
    try:
        await refresh_waiters_at_start(services)

        async def seen():
            return len(waiter_events(events)) >= 1

        await until(seen, timeout=2.0)
        assert waiter_events(events)[-1]["data"]["waiters"][0]["handle"] == "eng"
    finally:
        listener.cancel()


class _Die:
    """A model that raises, so the run fails and no reply is posted."""

    def __iter__(self):
        return self

    def __next__(self):
        raise RuntimeError("boom")
