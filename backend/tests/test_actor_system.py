import asyncio

from sqlalchemy import select

from openbot.db.models import Actor, InboxItem, Message, Run
from openbot.runtime.actors import BotActor
from openbot.runtime.delivery import create_thread, human_actor, post_message
from tests.conftest import build_test_services
from tests.factories import bot_actor
from tests.fakes import ScriptedChatModel, ai, call


async def setup(settings, scripts, handles=("eng",)):
    services = await build_test_services(settings, scripts)
    async with services.session_factory() as s:
        s.add_all([bot_actor(h) for h in handles])
        await s.commit()
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=list(handles), created_by=you)
    await services.actors.start()
    return services, t


async def post(services, t, text):
    async with services.session_factory() as s:
        you = await human_actor(s)
        return await post_message(services, s, thread_id=t.id, sender=you, content=text)


async def until(check, timeout=5.0, interval=0.02):
    """Poll `check` until it returns something truthy. A fixed sleep is a coin flip on a loaded
    machine (and in CI); this waits for the condition instead and only fails after `timeout`."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    result = None
    while loop.time() < deadline:
        result = await check()
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s (last value: {result!r})")


async def runs(services):
    async with services.session_factory() as s:
        return (await s.execute(select(Run).order_by(Run.created_at))).scalars().all()


async def items(services, kind=None):
    async with services.session_factory() as s:
        q = select(InboxItem).order_by(InboxItem.created_at)
        if kind:
            q = q.where(InboxItem.kind == kind)
        return (await s.execute(q)).scalars().all()


async def test_message_triggers_run_and_marks_item_done(settings):
    services, t = await setup(settings, {"eng": [ai("one")]})
    await post(services, t, "hi")
    await services.actors.wait_idle()
    rs = await runs(services)
    assert [r.status for r in rs] == ["completed"]
    bot_items = [i for i in await items(services, "message") if i.run_id == rs[0].id]
    assert len(bot_items) == 1 and bot_items[0].status == "done"
    await services.actors.stop()


async def test_batching_and_parking(settings):
    ScriptedChatModel.seen.clear()
    services, t = await setup(settings, {"eng": [ai(tool_calls=[call("ask_human", question="?")]), ai("after"), ai("batched")]})
    await post(services, t, "one")
    await services.actors.wait_idle()
    assert [r.status for r in await runs(services)] == ["waiting_human"]
    await post(services, t, "two")
    await post(services, t, "three")
    await services.actors.wait_idle()
    assert [r.status for r in await runs(services)] == ["waiting_human"]      # parked thread: new mail waits
    first = (await runs(services))[0]
    await services.actors.enqueue_resume(first, "yes", None)
    await services.actors.wait_idle()
    rs = await runs(services)
    assert [r.status for r in rs] == ["completed", "completed"]              # resume, then ONE batched run for two+three
    batched_items = [i for i in await items(services, "message") if i.run_id == rs[1].id]
    assert len(batched_items) == 2 and all(i.status == "done" for i in batched_items)
    # The batched human turn, not seen[-1][-1]: history is chronological, and the resumed run's own
    # "after" reply is posted after "two"/"three" (which waited while the thread was parked).
    last_prompt = next(m.content for m in ScriptedChatModel.seen[-1] if m.type == "human")
    assert "[You] (new): two" in last_prompt and "[You] (new): three" in last_prompt   # both coalesced triggers are marked
    await services.actors.stop()


async def test_one_run_at_a_time_per_bot_but_bots_parallel(settings):
    from langchain_core.messages import AIMessage

    class Slow:
        def __iter__(self):
            return self

        def __next__(self):
            import time
            time.sleep(1.0)            # wide enough that both runs are still "running" when polled
            return AIMessage(content="late")

    services, t = await setup(settings, {}, handles=("eng", "rev"))
    services.model_factory = lambda actor: ScriptedChatModel(messages=Slow())
    await post(services, t, "@eng @rev go")

    async def both_running():
        rs = [r for r in await runs(services) if r.status == "running"]
        return rs if len(rs) == 2 else None

    assert len(await until(both_running, timeout=2.0)) == 2
    await services.actors.wait_idle()
    await services.actors.stop()


async def test_cancel_running(settings):
    from langchain_core.messages import AIMessage

    class Slow:
        def __iter__(self):
            return self

        def __next__(self):
            import time
            time.sleep(1.0)
            return AIMessage(content="late")

    services, t = await setup(settings, {})
    services.model_factory = lambda actor: ScriptedChatModel(messages=Slow())
    await post(services, t, "go")

    async def running():
        return next((r for r in await runs(services) if r.status == "running"), None)

    run = await until(running, timeout=2.0)
    assert await services.actors.cancel_run(run.id) is True
    await services.actors.wait_idle()
    assert (await runs(services))[0].status == "cancelled"
    assert [i.status for i in await items(services, "message") if i.run_id == run.id] == ["cancelled"]
    await services.actors.stop()


async def test_recovery_on_start(settings):
    services = await build_test_services(settings, {"eng": [ai("recovered")]})
    async with services.session_factory() as s:
        eng = bot_actor("eng")
        s.add(eng)
        await s.commit()
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you)
        await post_message(services, s, thread_id=t.id, sender=you, content="hi")     # actors not started: item stays queued
        stale = Run(actor_id=eng.id, thread_id=t.id, status="running")
        s.add(stale)
        # _pick commits the run as "queued" with its items already "processing", before the
        # semaphore and the runner. A shutdown in that window used to leave the run queued forever:
        # nothing picks it up, it blocks DELETE /bots/{id} with 409, and it draws a phantom active
        # card. No worker exists during start(), so a queued run is provably orphaned.
        orphan = Run(actor_id=eng.id, thread_id=t.id, status="queued")
        s.add(orphan)
        await s.flush()
        s.add(InboxItem(actor_id=eng.id, thread_id=t.id, kind="message", status="processing", run_id=stale.id))
        s.add(InboxItem(actor_id=eng.id, thread_id=t.id, kind="message", status="processing", run_id=orphan.id))
        await s.commit()
        stale_id, orphan_id = stale.id, orphan.id
    await services.actors.start()
    await services.actors.wait_idle()
    rs = await runs(services)
    by_id = {r.id: r for r in rs}
    assert by_id[stale_id].status == "failed" and by_id[stale_id].error == "server restarted"
    assert by_id[orphan_id].status == "failed" and by_id[orphan_id].error == "server restarted"
    assert not [r for r in rs if r.status == "queued"]            # no ghost left behind
    assert [r.status for r in rs if r.id not in (stale_id, orphan_id)] == ["completed"]
    async with services.session_factory() as s:
        settled = (await s.execute(select(InboxItem).where(InboxItem.run_id.in_([stale_id, orphan_id])))).scalars().all()
    assert [i.status for i in settled] == ["done", "done"]
    # A failed run draws no card in the thread, so the interruption has to be said out loud or the
    # reader is left staring at their own unanswered message. Both orphans get the same notice.
    async with services.session_factory() as s:
        notices = [m.content for m in (await s.execute(select(Message).where(Message.thread_id == t.id))).scalars()
                   if m.sender_kind == "system"]
    assert notices == ["@eng run was interrupted by a server restart."] * 2
    await services.actors.stop()


async def test_concurrent_notify_creates_one_worker(settings, monkeypatch):
    services, _t = await setup(settings, {"eng": [ai("one")]})
    async with services.session_factory() as s:
        eng = (await s.execute(select(Actor).where(Actor.handle == "eng"))).scalar_one()
    started: list[BotActor] = []
    original_start = BotActor.start

    def spy(self):
        started.append(self)
        original_start(self)

    monkeypatch.setattr(BotActor, "start", spy)
    # notify() awaits a DB session before registering the worker: concurrent calls must not race.
    await asyncio.gather(*(services.actors.notify(eng.id) for _ in range(5)))
    assert len(started) == 1 and len(services.actors._workers) == 1
    assert services.actors._workers[eng.id] is started[0]
    await services.actors.stop()


async def test_drain_survives_item_bookkeeping_failure(settings):
    services = await build_test_services(settings, {"eng": [ai("one"), ai("two")]})
    async with services.session_factory() as s:
        s.add(bot_actor("eng"))
        await s.commit()
        you = await human_actor(s)
        t1 = await create_thread(services, s, title="t1", handles=["eng"], created_by=you)
        t2 = await create_thread(services, s, title="t2", handles=["eng"], created_by=you)
        await post_message(services, s, thread_id=t1.id, sender=you, content="one")
        await post_message(services, s, thread_id=t2.id, sender=you, content="two")
    real_factory, real_execute, armed = services.session_factory, services.runner.execute, {"on": False}

    def factory():
        if armed["on"]:                     # the first session opened after a run is _process's finally
            armed["on"] = False
            raise RuntimeError("bookkeeping db failure")
        return real_factory()

    async def execute(run_id, resume=None):
        await real_execute(run_id, resume=resume)
        armed["on"] = True

    services.runner.execute, services.session_factory = execute, factory
    await services.actors.start()
    await services.actors.wait_idle()
    rs = await runs(services)
    # batch 1's bookkeeping blew up, but the drain kept going and still picked up batch 2
    assert [r.thread_id for r in rs] == [t1.id, t2.id]
    assert [r.status for r in rs] == ["completed", "completed"]
    await services.actors.stop()


async def test_run_is_created_only_when_a_slot_is_free(settings):
    """Under load a bot used to create its run (and flip its items to processing) and then sit on
    the semaphore, leaving a phantom queued run that blocked bot deletion and drew an active card.
    Now the slot comes first: a waiting bot has no run row and its items stay queued."""
    from langchain_core.messages import AIMessage

    class Slow:
        def __iter__(self):
            return self

        def __next__(self):
            import time
            time.sleep(0.6)
            return AIMessage(content="late")

    settings.max_concurrent_runs = 1
    services, t = await setup(settings, {}, handles=("eng", "rev"))
    services.model_factory = lambda actor: ScriptedChatModel(messages=Slow())
    await post(services, t, "@eng @rev go")

    async def one_running():
        rs = await runs(services)
        return rs if any(r.status == "running" for r in rs) else None

    rs = await until(one_running, timeout=2.0)
    assert [r.status for r in rs] == ["running"]          # exactly one run row exists, and it is live
    async with services.session_factory() as s:
        waiting = (await s.execute(select(InboxItem).where(InboxItem.status == "queued", InboxItem.kind == "message"))).scalars().all()
        bots = {a.id: a.handle for a in (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars()}
    assert len(waiting) == 1 and bots[waiting[0].actor_id] != bots[rs[0].actor_id]
    await services.actors.wait_idle()
    assert sorted(r.status for r in await runs(services)) == ["completed", "completed"]
    await services.actors.stop()
