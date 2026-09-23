import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openbot.db.models import Actor, Message, ScheduledMessage, utcnow
from openbot.runtime.delivery import create_thread, human_actor
from openbot.runtime.scheduler import Scheduler, recover_processing


async def _job(services, *, due_at=None, status="pending", content="check CI"):
    async with services.session_factory() as session:
        you = await human_actor(session)
        session.add(Actor(handle="eng", name="Engineer", kind="bot", enabled=True))
        await session.flush()
        thread = await create_thread(services, session, title="scheduled", handles=["eng"], created_by=you)
        job = ScheduledMessage(
            thread_id=thread.id,
            sender_actor_id=you.id,
            to_handles=["eng"],
            content=content,
            due_at=due_at or (utcnow() - timedelta(seconds=1)),
            status=status,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job.id


async def _get(services, job_id):
    async with services.session_factory() as session:
        return await session.get(ScheduledMessage, job_id)


@pytest.mark.asyncio
async def test_two_workers_atomically_claim_once(services, monkeypatch):
    calls = []
    job_id = await _job(services)

    async def deliver(*args, **kwargs):
        calls.append(job_id)
        return SimpleNamespace(message=Message(id="result", thread_id=kwargs["thread_id"],
                                                sender_kind="human", sender_name="you", content="check CI"))

    monkeypatch.setattr("openbot.runtime.scheduler.post_message", deliver)
    await asyncio.gather(Scheduler(services).run_due(), Scheduler(services).run_due())
    assert calls == [job_id]
    job = await _get(services, job_id)
    assert job.status == "delivered" and job.attempts == 1


@pytest.mark.asyncio
async def test_restart_recovers_processing_jobs(services):
    job_id = await _job(services, status="processing")
    await recover_processing(services)
    job = await _get(services, job_id)
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_retries_then_terminal_failure_is_inspectable(services, monkeypatch):
    job_id = await _job(services)
    calls = 0

    async def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("openbot.runtime.scheduler.post_message", fail)
    worker = Scheduler(services)
    await worker.run_due()
    await worker.run_due()
    await worker.run_due()
    job = await _get(services, job_id)
    assert calls == 3
    assert job.status == "failed" and job.attempts == 3
    assert job.last_error == "provider unavailable"


@pytest.mark.asyncio
async def test_cancelled_jobs_are_not_delivered(services, monkeypatch):
    job_id = await _job(services, status="cancelled")
    called = False

    async def deliver(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("openbot.runtime.scheduler.post_message", deliver)
    await Scheduler(services).run_due()
    assert called is False
    assert (await _get(services, job_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_due_delivery_records_result_message(services, monkeypatch):
    job_id = await _job(services, content="check the CI")
    result = Message(id="message-result", thread_id="unused", sender_kind="human", sender_name="you",
                     content="check the CI")

    async def deliver(*args, **kwargs):
        assert kwargs["content"] == "check the CI"
        return SimpleNamespace(message=result)

    monkeypatch.setattr("openbot.runtime.scheduler.post_message", deliver)
    await Scheduler(services).run_due()
    job = await _get(services, job_id)
    assert job.status == "delivered"
    assert job.result_message_id == "message-result"


@pytest.mark.asyncio
async def test_future_jobs_remain_pending(services):
    job_id = await _job(services, due_at=datetime.now(UTC) + timedelta(hours=1))
    await Scheduler(services).run_due()
    job = await _get(services, job_id)
    assert job.status == "pending" and job.attempts == 0


@pytest.mark.asyncio
async def test_delivery_is_idempotent_after_message_commit(services, monkeypatch):
    job_id = await _job(services, status="processing")
    async with services.session_factory() as session:
        job = await session.get(ScheduledMessage, job_id)
        message = Message(thread_id=job.thread_id, sender_kind="human", sender_name="you",
                          content=job.content, meta={"scheduled_message_id": job.id})
        session.add(message)
        await session.commit()
    deliver = AsyncMock()
    monkeypatch.setattr("openbot.runtime.scheduler.post_message", deliver)
    await Scheduler(services)._deliver(job_id)
    job = await _get(services, job_id)
    assert job.status == "delivered" and job.result_message_id == message.id
    deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_state_transitions_publish_sse_updates(services, monkeypatch):
    await _job(services)
    published = []
    async def publish(event, thread_id, payload):
        published.append((event, thread_id, payload))
    monkeypatch.setattr(services.bus, "publish", publish)
    result = Message(id="result", thread_id="unused", sender_kind="human", sender_name="you", content="check CI")
    async def deliver(*args, **kwargs):
        return SimpleNamespace(message=result)
    monkeypatch.setattr("openbot.runtime.scheduler.post_message", deliver)
    await Scheduler(services).run_due()
    assert published[-1][0] == "scheduled.updated"
    assert published[-1][2]["status"] == "delivered"


@pytest.mark.asyncio
async def test_retry_and_terminal_failure_publish_sse_updates(services, monkeypatch):
    await _job(services)
    published = []
    async def publish(event, thread_id, payload):
        published.append(payload)
    monkeypatch.setattr(services.bus, "publish", publish)
    async def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr("openbot.runtime.scheduler.post_message", fail)
    worker = Scheduler(services)
    await worker.run_due()
    await worker.run_due()
    await worker.run_due()
    assert [p["status"] for p in published] == ["pending", "pending", "failed"]
