"""Deleting a thread stops its work and hides it, but keeps every row for investigation."""
import asyncio
from datetime import timedelta

from sqlalchemy import select

from openbot.db.models import ActivityLog, InboxItem, Message, Run, ScheduledMessage, Thread, utcnow
from openbot.runtime.delivery import human_actor
from tests.test_actor_system import StreamThenStall, items, post, runs, setup, until
from tests.test_runner import make

BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5"}


async def test_delete_hides_the_thread_but_keeps_its_rows(client, services):
    await client.post("/api/v1/bots", json=BOT)
    t = (await client.post("/api/v1/threads", json={"title": "Work", "handles": ["eng"]})).json()
    assert (await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "hello"})).status_code == 201
    if services.actors:
        await services.actors.wait_idle()

    assert (await client.delete(f"/api/v1/threads/{t['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/threads/{t['id']}")).status_code == 404
    assert t["id"] not in [x["id"] for x in (await client.get("/api/v1/threads")).json()]
    assert (await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "again"})).status_code == 404
    assert (await client.delete(f"/api/v1/threads/{t['id']}")).status_code == 404

    async with services.session_factory() as s:
        thread = await s.get(Thread, t["id"])
        assert thread is not None and thread.deleted_at is not None
        contents = (await s.execute(select(Message.content).where(Message.thread_id == t["id"]))).scalars().all()
        assert "hello" in contents
        events = (await s.execute(select(ActivityLog.event).where(ActivityLog.thread_id == t["id"]))).scalars().all()
    assert "thread.deleted" in events


async def test_delete_cancels_queued_mail_and_scheduled_messages(client, services):
    await client.post("/api/v1/bots", json=BOT)
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    async with services.session_factory() as s:
        you = await human_actor(s)          # nothing works a human's inbox, so the item stays queued
        s.add(InboxItem(actor_id=you.id, thread_id=t["id"], kind="message", status="queued"))
        s.add(ScheduledMessage(thread_id=t["id"], sender_actor_id=you.id, content="later", to_handles=["eng"],
                               due_at=utcnow() + timedelta(days=1)))
        await s.commit()
    assert (await client.delete(f"/api/v1/threads/{t['id']}")).status_code == 204
    async with services.session_factory() as s:
        statuses = (await s.execute(select(InboxItem.status).where(InboxItem.thread_id == t["id"]))).scalars().all()
        jobs = (await s.execute(select(ScheduledMessage.status).where(ScheduledMessage.thread_id == t["id"]))).scalars().all()
    assert "queued" not in statuses and jobs == ["cancelled"]


async def test_delete_cancels_a_live_run_instead_of_leaving_it_to_crash(settings):
    services, t = await setup(settings, {})
    services.model_factory = lambda actor: StreamThenStall(messages=["working on it"])
    await post(services, t, "@eng go")

    async def running():
        return next((r for r in await runs(services) if r.status == "running"), None)

    run = await until(running, timeout=5.0)
    stopped = await services.actors.close_thread(t.id)
    assert stopped["cancelled_runs"] == 1
    await asyncio.wait_for(services.actors.wait_idle(), 10)
    [after] = await runs(services)
    assert after.id == run.id and after.status == "cancelled"
    assert all(i.status != "queued" for i in await items(services))
    async with services.session_factory() as s:
        crashes = (await s.execute(select(ActivityLog).where(ActivityLog.run_id == run.id,
                                                             ActivityLog.summary.like("%crashed%")))).scalars().all()
    assert crashes == []
    await services.actors.stop()


async def test_a_run_picked_up_after_the_delete_does_not_start(settings):
    services, _eng, t, run = await make(settings, {"eng": []})
    async with services.session_factory() as s:
        (await s.get(Thread, t.id)).deleted_at = utcnow()
        await s.commit()
    await services.runner.execute(run.id)
    async with services.session_factory() as s:
        run = await s.get(Run, run.id)
    assert run.status == "cancelled" and run.error == "thread was deleted"
