from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, update

from openbot.db.models import Message, ScheduledMessage, utcnow
from openbot.runtime.delivery import cron_actor, post_message

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, services):
        self.services = services
        self.task: asyncio.Task | None = None
        self.running = False

    async def start(self):
        self.running = True
        self.task = asyncio.create_task(self._loop(), name="scheduled-messages")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def _loop(self):
        while self.running:
            try:
                await self.run_due()
            except Exception:
                log.exception("scheduled message sweep failed")
            await asyncio.sleep(1)

    async def run_due(self):
        async with self.services.session_factory() as session:
            ids = (await session.execute(select(ScheduledMessage.id).where(
                ScheduledMessage.status == "pending", ScheduledMessage.due_at <= utcnow()
            ).order_by(ScheduledMessage.due_at).limit(20))).scalars().all()
        claimed: list[str] = []
        for job_id in ids:
            async with self.services.session_factory() as session:
                result = await session.execute(update(ScheduledMessage).where(
                    ScheduledMessage.id == job_id,
                    ScheduledMessage.status == "pending",
                    ScheduledMessage.due_at <= utcnow(),
                ).values(status="processing", attempts=ScheduledMessage.attempts + 1))
                await session.commit()
                if result.rowcount == 1:
                    claimed.append(job_id)
        for job_id in claimed:
            await self._deliver(job_id)

    async def _deliver(self, job_id: str):
        async with self.services.session_factory() as session:
            job = await session.get(ScheduledMessage, job_id)
            if not job or job.status != "processing":
                return
            try:
                # post_message commits independently. If the process dies after that
                # commit but before recording the job, do not post a duplicate.
                messages = (await session.execute(
                    select(Message).where(Message.thread_id == job.thread_id)
                    .order_by(Message.created_at.desc())
                )).scalars().all()
                existing = next((m for m in messages
                                 if (m.meta or {}).get("scheduled_message_id") == job.id), None)
                if existing is not None:
                    job.status, job.result_message_id = "delivered", existing.id
                    job.last_error = None
                    await session.commit()
                    await self._publish(job)
                    return
                # Delivered by @cron, not by whoever scheduled it: the requester's own turn ended long
                # ago, so posting under its identity would make a bot appear to speak without a live run
                # backing it -- and, for a self-addressed reminder, would make it the target of its own
                # message, which resolve_targets refuses to wake (see router.resolve_targets).
                sender = await cron_actor(session)
                result = await post_message(
                    self.services, session, thread_id=job.thread_id, sender=sender,
                    content=job.content, to_handles=job.to_handles,
                    meta={"scheduled_message_id": job.id},
                )
                job.status, job.result_message_id = "delivered", result.message.id
                job.last_error = None
                await session.commit()
                await self._publish(job)
            except Exception as exc:  # noqa: BLE001 - delivery providers may raise arbitrary errors
                job.last_error = str(exc)
                job.status = "pending" if job.attempts < 3 else "failed"
                await session.commit()
                await self._publish(job)
                log.warning("scheduled message %s failed (attempt %s): %s", job.id, job.attempts, exc)

    async def _publish(self, job: ScheduledMessage) -> None:
        """Publish after persistence; event failure must not change job state."""
        try:
            await self.services.bus.publish(
                "scheduled.updated", job.thread_id,
                {"id": job.id, "status": job.status, "attempts": job.attempts,
                 "result_message_id": job.result_message_id, "last_error": job.last_error},
            )
        except Exception:
            log.exception("could not publish scheduled update for %s", job.id)


async def recover_processing(services):
    async with services.session_factory() as session:
        await session.execute(update(ScheduledMessage).where(
            ScheduledMessage.status == "processing"
        ).values(status="pending"))
        await session.commit()
