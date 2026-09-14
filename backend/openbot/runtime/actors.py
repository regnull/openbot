from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

import httpx
from langgraph.types import Command
from sqlalchemy import select

from openbot.api.schemas import InboxItemOut, MessageOut, RunOut, to_json
from openbot.db.models import Actor, InboxItem, Message, Run, utcnow
from openbot.runtime.delivery import post_message

log = logging.getLogger(__name__)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def webhook_body(item: InboxItem, message: Message | None) -> dict:
    return {"item_id": item.id, "kind": item.kind, "thread_id": item.thread_id,
            "message": to_json(MessageOut, message) if message else None,
            "question": item.payload if item.kind == "question" else None,
            "created_at": item.created_at.isoformat()}


@dataclass
class Batch:
    run_id: str
    items: list[InboxItem]
    resume: object | None = None   # value to resume with, or None for a fresh run


class _Worker:
    def __init__(self, system: ActorSystem, actor_id: str) -> None:
        self.system = system
        self.actor_id = actor_id
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.busy = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name=f"actor:{self.actor_id}")

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            self.busy = True
            try:
                await self._drain()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("actor %s worker error", self.actor_id)
            finally:
                self.busy = False

    async def _drain(self) -> None:
        raise NotImplementedError

    @property
    def idle(self) -> bool:
        return not self.busy and not self._wake.is_set()


class BotActor(_Worker):
    def __init__(self, system: ActorSystem, actor_id: str) -> None:
        super().__init__(system, actor_id)
        self.current_run_id: str | None = None
        self.current_task: asyncio.Task | None = None

    async def _drain(self) -> None:
        while (batch := await self._pick()) is not None:
            async with self.system.sem:
                await self._process(batch)

    async def _pick(self) -> Batch | None:
        s = self.system.s
        async with s.session_factory() as session:
            items = (await session.execute(select(InboxItem).where(InboxItem.actor_id == self.actor_id, InboxItem.status == "queued")
                                           .order_by(InboxItem.created_at))).scalars().all()
            if not items:
                return None
            parked = set((await session.execute(select(Run.thread_id).where(Run.actor_id == self.actor_id, Run.status == "waiting_human"))).scalars().all())
            chosen = next((i for i in items if not (i.kind == "message" and i.thread_id in parked)), None)
            if chosen is None:
                return None
            if chosen.kind == "resume":
                chosen.status = "processing"
                await session.commit()
                return Batch(run_id=chosen.run_id, items=[chosen], resume=chosen.payload.get("resume"))
            group = [i for i in items if i.kind == "message" and i.thread_id == chosen.thread_id]
            run = Run(actor_id=self.actor_id, thread_id=chosen.thread_id, status="queued")
            session.add(run)
            await session.flush()
            for i in group:
                i.status, i.run_id = "processing", run.id
            await session.commit()
            await s.bus.publish("run.updated", run.thread_id, to_json(RunOut, run))
            return Batch(run_id=run.id, items=group)

    async def _process(self, batch: Batch) -> None:
        s = self.system.s
        cmd = Command(resume=batch.resume) if batch.resume is not None else None
        self.current_run_id = batch.run_id
        self.current_task = asyncio.create_task(s.runner.execute(batch.run_id, resume=cmd))
        status = "done"
        try:
            await self.current_task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            status = "cancelled"
        except Exception:
            log.exception("run %s crashed", batch.run_id)
        finally:
            self.current_task, self.current_run_id = None, None
            rows: list[InboxItem] = []
            try:
                async with s.session_factory() as session:
                    # Only items still "processing": a cancel_run that raced _pick already settled
                    # them as "cancelled", and that must not be overwritten with "done".
                    rows = (await session.execute(select(InboxItem).where(InboxItem.id.in_([i.id for i in batch.items]),
                                                                          InboxItem.status == "processing"))).scalars().all()
                    for i in rows:
                        i.status, i.processed_at = status, utcnow()
                    await session.commit()
                for i in rows:
                    await s.bus.publish("inbox.updated", i.thread_id, to_json(InboxItemOut, i))
            except Exception:
                # Best-effort: bookkeeping must never abort the drain or mask the run's own error.
                # Items left "processing" are requeued by recovery on the next start().
                log.exception("failed to finalize inbox items for run %s", batch.run_id)


class ExternalActor(_Worker):
    async def _drain(self) -> None:
        while (item := await self._pick()) is not None:
            await self._deliver(item)

    async def _pick(self) -> InboxItem | None:
        async with self.system.s.session_factory() as session:
            actor = await session.get(Actor, self.actor_id)
            if not actor or not actor.external or not actor.external.webhook_url:
                return None
            item = (await session.execute(select(InboxItem).where(InboxItem.actor_id == self.actor_id, InboxItem.status == "queued",
                                                                 InboxItem.kind.in_(["message", "question"]))
                                          .order_by(InboxItem.created_at).limit(1))).scalar_one_or_none()
            if item is None:
                return None
            item.status = "processing"
            await session.commit()
            return item

    async def _deliver(self, item: InboxItem) -> None:
        s = self.system.s
        async with s.session_factory() as session:
            actor = await session.get(Actor, self.actor_id)
            message = await session.get(Message, item.message_id) if item.message_id else None
        url = actor.external.webhook_url if actor and actor.external else None
        if not url:
            # The actor lost its webhook between _pick and here; settle the item so it is not
            # left "processing" forever and _drain can move on.
            await self._update(item.id, "failed", 0, "no webhook url")
            return
        secret = actor.external.webhook_secret or ""
        body = json.dumps(webhook_body(item, message), default=str).encode()
        headers = {"Content-Type": "application/json", "X-OpenBot-Kind": item.kind, "X-OpenBot-Item": item.id,
                   "X-OpenBot-Signature": sign(secret, body)}
        delays = [0.0, *s.settings.webhook_retry_delays]
        last_error = None
        for attempt, delay in enumerate(delays, start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                r = await s.http_client.post(url, content=body, headers=headers)
                ok, last_error = r.status_code < 300, None if r.status_code < 300 else f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                ok, last_error = False, f"{type(e).__name__}: {e}"
            await self._update(item.id, "done" if ok else "processing", attempt, last_error)
            if ok:
                return
        await self._update(item.id, "failed", len(delays), last_error)

    async def _update(self, item_id: str, status: str, attempts: int, error: str | None) -> None:
        s = self.system.s
        async with s.session_factory() as session:
            it = await session.get(InboxItem, item_id)
            it.status, it.attempts, it.last_error = status, attempts, error
            if status in ("done", "failed"):
                it.processed_at = utcnow()
            await session.commit()
        if status in ("done", "failed"):
            await s.bus.publish("inbox.updated", it.thread_id, to_json(InboxItemOut, it))


class ActorSystem:
    def __init__(self, services, max_concurrent: int) -> None:
        self.s = services
        self.sem = asyncio.Semaphore(max_concurrent)
        self._workers: dict[str, _Worker] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        interrupted: list[tuple[str, str]] = []
        async with self.s.session_factory() as session:
            for run in (await session.execute(select(Run).where(Run.status == "running"))).scalars():
                run.status, run.error, run.finished_at = "failed", "server restarted", utcnow()
                bot = await session.get(Actor, run.actor_id)
                interrupted.append((run.thread_id, bot.handle if bot else "bot"))
                for it in (await session.execute(select(InboxItem).where(InboxItem.run_id == run.id, InboxItem.status == "processing"))).scalars():
                    it.status, it.processed_at = "done", utcnow()
            for it in (await session.execute(select(InboxItem).where(InboxItem.status == "processing"))).scalars():
                it.status = "queued"
            await session.commit()
            pending = (await session.execute(select(InboxItem.actor_id).where(InboxItem.status == "queued").distinct())).scalars().all()
        # A failed run draws no card in the thread, so without this a run killed by a restart leaves
        # the reader staring at their own unanswered message. The runner says so for every other
        # failure; say it here too.
        for thread_id, handle in interrupted:
            log.info("run for @%s in thread %s was interrupted by a restart", handle, thread_id)
            try:
                async with self.s.session_factory() as session:
                    await post_message(self.s, session, thread_id=thread_id, sender=None,
                                       content=f"@{handle} run was interrupted by a server restart.")
            except Exception:
                log.exception("could not post the restart notice for thread %s", thread_id)
        for aid in pending:
            await self.notify(aid)

    async def stop(self) -> None:
        self._started = False
        workers, self._workers = list(self._workers.values()), {}
        for w in workers:
            await w.stop()

    async def notify(self, actor_id: str) -> None:
        if not self._started:
            return
        w = self._workers.get(actor_id)
        if w is None:
            async with self.s.session_factory() as session:
                actor = await session.get(Actor, actor_id)
            if actor is None or actor.kind == "human" or not self._started:
                return
            # Re-check after the await: a concurrent notify() for the same actor reaches here too, and
            # a second worker would mean two concurrent runs for one bot plus a task stop() never sees.
            w = self._workers.get(actor_id)
            if w is None:
                w = BotActor(self, actor_id) if actor.kind == "bot" else ExternalActor(self, actor_id)
                self._workers[actor_id] = w
                w.start()
        w.wake()

    async def cancel_run(self, run_id: str) -> bool:
        for w in self._workers.values():
            if isinstance(w, BotActor) and w.current_run_id == run_id and w.current_task:
                w.current_task.cancel()
                return True
        async with self.s.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None or run.status not in ("queued", "waiting_human"):
                return False
            run.status, run.finished_at = "cancelled", utcnow()
            items = (await session.execute(select(InboxItem).where(InboxItem.run_id == run_id, InboxItem.status.in_(["queued", "processing"])))).scalars().all()
            for i in items:
                i.status, i.processed_at = "cancelled", utcnow()
            await session.commit()
            await self.s.bus.publish("run.updated", run.thread_id, to_json(RunOut, run))
        await self.notify(run.actor_id)     # parked thread may now have waiting mail
        return True

    async def enqueue_resume(self, run: Run, value, from_actor: Actor | None) -> InboxItem:
        async with self.s.session_factory() as session:
            item = InboxItem(actor_id=run.actor_id, thread_id=run.thread_id, kind="resume", run_id=run.id,
                             payload={"resume": value, "from": from_actor.handle if from_actor else None})
            session.add(item)
            await session.commit()
        await self.s.bus.publish("inbox.updated", item.thread_id, to_json(InboxItemOut, item))
        await self.notify(run.actor_id)
        return item

    async def wait_idle(self, timeout: float = 30.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            await asyncio.sleep(0.02)
            if all(w.idle for w in self._workers.values()):
                await asyncio.sleep(0.02)
                if all(w.idle for w in self._workers.values()):
                    return
        raise TimeoutError("actor system did not become idle")
