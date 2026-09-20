"""The activity log: every step a message takes through a thread and a bot's inbox (delivery,
queueing, pickup, run status, settlement) is recorded in the database so a stalled thread can be
debugged after the fact from the data alone."""
import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import inspect, select

from openbot.db.models import ActivityLog, Actor, Run, utcnow
from openbot.db.session import make_engine, run_migrations
from openbot.runtime import activity
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.services import Services
from tests.conftest import build_test_services
from tests.factories import bot_actor
from tests.fakes import ai, call


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


async def rows(services, **where):
    async with services.session_factory() as s:
        q = select(ActivityLog).order_by(ActivityLog.id)
        for k, v in where.items():
            q = q.where(getattr(ActivityLog, k) == v)
        return (await s.execute(q)).scalars().all()


async def until(check, timeout=5.0, interval=0.02):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    result = None
    while loop.time() < deadline:
        result = await check()
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s (last value: {result!r})")


def events(entries) -> list[str]:
    return [e.event for e in entries]


async def test_message_lifecycle_is_recorded_in_order(settings):
    services, t = await setup(settings, {"eng": [ai("one")]})
    res = await post(services, t, "hi @eng")
    await services.actors.wait_idle()
    log = await rows(services, thread_id=t.id)
    names = events(log)
    order = ["thread.created", "message.posted", "inbox.enqueued", "worker.notified", "run.created",
             "run.status", "run.started", "run.model_call", "message.posted", "run.status", "run.finished", "inbox.settled"]
    positions = []
    start = 0
    for name in order:
        assert name in names[start:], f"{name} missing after position {start}: {names}"
        idx = names.index(name, start)
        positions.append(idx)
        start = idx + 1
    posted = next(e for e in log if e.event == "message.posted")
    assert posted.message_id == res.message.id and posted.detail["addressed"] == ["eng"] and posted.detail["sender"] == "you"
    enqueued = next(e for e in log if e.event == "inbox.enqueued")
    assert enqueued.item_id == res.items[0].id and enqueued.detail["kind"] == "message"
    async with services.session_factory() as s:
        run = (await s.execute(select(Run))).scalar_one()
    created = next(e for e in log if e.event == "run.created")
    assert created.run_id == run.id and created.actor_id == run.actor_id and created.detail["item_ids"] == [res.items[0].id]
    statuses = [e.detail["status"] for e in log if e.event == "run.status"]
    assert statuses == ["running", "completed"]
    settled = next(e for e in log if e.event == "inbox.settled")
    assert settled.detail["status"] == "done" and settled.detail["item_ids"] == [res.items[0].id]
    assert all(e.created_at is not None for e in log)
    assert {e.level for e in log if e.event in ("message.posted", "run.created", "run.status")} == {"info"}
    await services.actors.stop()


async def test_parked_thread_pickup_is_recorded(settings):
    services, t = await setup(settings, {"eng": [ai(tool_calls=[call("ask_human", question="?")]), ai("after")]})
    await post(services, t, "one")
    await services.actors.wait_idle()
    second = await post(services, t, "two")
    await services.actors.wait_idle()
    parked = [e for e in await rows(services, event="worker.parked")]
    assert parked, events(await rows(services))
    e = parked[-1]
    assert e.thread_id is None and e.level == "warning"
    assert second.items[0].id in e.detail["queued_item_ids"] and t.id in e.detail["parked_thread_ids"]
    assert e.detail["queued"] == 1
    await services.actors.stop()


async def test_waiting_for_a_concurrency_slot_is_recorded(settings):
    settings.max_concurrent_runs = 1
    services, t = await setup(settings, {"eng": [ai("one")]})
    await services.actors.sem.acquire()          # somebody else holds the only slot
    try:
        await post(services, t, "hi")
        waited = await until(lambda: rows(services, event="worker.slot.wait"))
        assert waited[0].actor_id is not None and waited[0].level == "warning"
        assert not await rows(services, event="run.created")
    finally:
        services.actors.sem.release()
    await services.actors.wait_idle()
    acquired = await rows(services, event="worker.slot.acquired")
    assert acquired and acquired[0].detail["waited_seconds"] >= 0
    assert await rows(services, event="run.created")
    await services.actors.stop()


async def test_failed_run_is_recorded_with_error(settings):
    services, t = await setup(settings, {"eng": [RuntimeError("boom")]})
    await post(services, t, "hi")
    await services.actors.wait_idle()
    failed = [e for e in await rows(services, event="run.status") if e.detail["status"] == "failed"]
    assert failed and failed[0].level == "error" and "boom" in failed[0].detail["error"]
    finished = await rows(services, event="run.finished")
    assert finished and finished[0].detail["status"] == "done"    # the actor's bookkeeping status, not the run's
    await services.actors.stop()


async def test_resume_and_question_are_recorded(settings):
    services, t = await setup(settings, {"eng": [ai(tool_calls=[call("ask_human", question="?")]), ai("after")]})
    await post(services, t, "one")
    await services.actors.wait_idle()
    assert await rows(services, event="question.delivered")
    assert [e.detail["status"] for e in await rows(services, event="run.status")] == ["running", "waiting_human"]
    async with services.session_factory() as s:
        run = (await s.execute(select(Run))).scalar_one()
    await services.actors.enqueue_resume(run, "yes", None)
    await services.actors.wait_idle()
    enq = [e for e in await rows(services, event="inbox.enqueued") if e.detail["kind"] == "resume"]
    assert enq and enq[0].run_id == run.id
    assert await rows(services, event="resume.picked")
    assert [e.detail["status"] for e in await rows(services, event="run.status")] == ["running", "waiting_human", "running", "completed"]
    await services.actors.stop()


async def test_cancel_is_recorded(settings):
    services, t = await setup(settings, {"eng": [ai(tool_calls=[call("ask_human", question="?")])]})
    await post(services, t, "one")
    await services.actors.wait_idle()
    async with services.session_factory() as s:
        run = (await s.execute(select(Run))).scalar_one()
    assert await services.actors.cancel_run(run.id)
    await services.actors.wait_idle()
    req = await rows(services, event="run.cancel_requested")
    assert req and req[0].run_id == run.id and req[0].detail["live"] is False
    assert [e.detail["status"] for e in await rows(services, event="run.status")][-1] == "cancelled"
    await services.actors.stop()


async def test_restart_recovery_is_recorded(settings):
    services, t = await setup(settings, {"eng": []})
    async with services.session_factory() as s:
        eng = (await s.execute(select(Actor).where(Actor.handle == "eng"))).scalar_one()
        s.add(Run(actor_id=eng.id, thread_id=t.id, status="running"))
        await s.commit()
    await services.actors.stop()
    await services.actors.start()
    rec = await rows(services, event="recovery.run_failed")
    assert rec and rec[0].thread_id == t.id
    assert await rows(services, event="system.started")
    await services.actors.stop()


async def test_record_never_raises(settings):
    class Broken:
        def __call__(self):
            raise RuntimeError("db down")

    services = Services(settings=settings, session_factory=Broken())
    assert await activity.record(services, "message.posted", summary="x", thread_id="t") is None


async def test_record_within_callers_session_commits_with_it(services):
    async with services.session_factory() as s:
        await activity.record(services, "thread.created", summary="in-tx", thread_id="t1", session=s)
        assert not await rows(services, thread_id="t1")     # nothing visible before the caller commits
        await s.commit()
    assert [e.summary for e in await rows(services, thread_id="t1")] == ["in-tx"]


async def test_prune_deletes_rows_older_than_retention(services):
    await activity.record(services, "system.started", summary="old")
    await activity.record(services, "system.started", summary="new")
    async with services.session_factory() as s:
        old = (await s.execute(select(ActivityLog).where(ActivityLog.summary == "old"))).scalar_one()
        old.created_at = utcnow() - timedelta(days=30)
        await s.commit()
    deleted = await activity.prune(services, days=14)
    assert deleted == 1
    summaries = [e.summary for e in await rows(services)]
    assert "new" in summaries and "old" not in summaries
    assert await activity.prune(services, days=0) == 0       # 0 keeps everything


async def test_activity_api_filters_and_pages(client, services):
    async with services.session_factory() as s:
        s.add(bot_actor("eng"))
        await s.commit()
    r = await client.post("/api/v1/threads", json={"title": "t", "handles": ["eng"]})
    t = r.json()
    await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "hi @eng"})
    await services.actors.wait_idle()
    r = await client.get("/api/v1/activity", params={"thread_id": t["id"]})
    assert r.status_code == 200
    body = r.json()
    assert body and body[0]["event"] == "thread.created" and all(e["thread_id"] == t["id"] for e in body)
    ids = [e["id"] for e in body]
    assert ids == sorted(ids)
    r = await client.get("/api/v1/activity", params={"event": "message.posted"})
    assert {e["event"] for e in r.json()} == {"message.posted"}
    r = await client.get("/api/v1/activity", params={"actor_id": body[-1]["actor_id"]})
    assert r.json() and all(e["actor_id"] == body[-1]["actor_id"] for e in r.json())
    r = await client.get("/api/v1/activity", params={"thread_id": t["id"], "limit": 2})
    assert [e["id"] for e in r.json()] == ids[-2:]     # the newest `limit` rows, oldest first
    r = await client.get("/api/v1/activity", params={"thread_id": t["id"], "after_id": ids[-3]})
    assert [e["id"] for e in r.json()] == ids[-2:]
    r = await client.get("/api/v1/activity", params={"thread_id": t["id"], "before_id": ids[2]})
    assert [e["id"] for e in r.json()] == ids[:2]
    r = await client.get("/api/v1/activity", params={"level": "debug"})
    assert r.json() and all(e["level"] == "debug" for e in r.json())
    r = await client.get("/api/v1/activity", params={"run_id": body[-1]["run_id"]})
    assert r.json() and all(e["run_id"] == body[-1]["run_id"] for e in r.json())
    r = await client.get("/api/v1/activity", params={"limit": 0})
    assert r.status_code == 422


async def test_migration_creates_activity_log_table(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("activity_log")})
        idx = await conn.run_sync(lambda c: {i["name"] for i in inspect(c).get_indexes("activity_log")})
    await engine.dispose()
    assert {"id", "created_at", "level", "event", "summary", "thread_id", "actor_id", "run_id", "item_id", "message_id", "detail"} <= cols
    assert {"ix_activity_thread", "ix_activity_actor", "ix_activity_run", "ix_activity_created"} <= idx


@pytest.mark.parametrize("bad", ["not.an.event", ""])
async def test_unknown_event_names_are_rejected_in_code(services, bad):
    with pytest.raises(ValueError):
        await activity.record(services, bad, summary="x")
