from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass

import httpx
from langgraph.types import Command
from sqlalchemy import select

from openbot.api.schemas import InboxItemOut, MessageOut, RunOut, to_json
from openbot.db.models import (
    OPEN_RUN_STATUSES,
    Actor,
    InboxItem,
    Message,
    Run,
    ThreadParticipant,
    utcnow,
)
from openbot.runtime import activity
from openbot.runtime.delivery import post_message
from openbot.runtime.waiters import publish_waiters, refresh_waiters_at_start

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
        self.drained = 0            # batches/items handled during the current drain, for the log

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
            self.drained = 0
            started = time.monotonic()
            await activity.record(self.system.s, "worker.drain.start", level="debug", actor_id=self.actor_id,
                                  summary="worker woke up and is draining its inbox")
            try:
                await self._drain()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("actor %s worker error", self.actor_id)
                await activity.record(self.system.s, "worker.error", level="error", actor_id=self.actor_id,
                                      summary=f"worker loop crashed: {type(e).__name__}: {e}"[:500],
                                      error=f"{type(e).__name__}: {e}"[:2000])
            finally:
                self.busy = False
                await activity.record(self.system.s, "worker.drain.end", level="debug", actor_id=self.actor_id,
                                      summary=f"worker went idle after {self.drained} item(s) in {time.monotonic() - started:.1f}s",
                                      drained=self.drained, seconds=round(time.monotonic() - started, 3))

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
        # Take the concurrency slot before picking: _pick creates the Run row and flips the items to
        # "processing", so picking first and then waiting on the semaphore left a phantom "queued"
        # run (blocking bot deletion, drawing an active card) for as long as the wait lasted.
        while True:
            sem = self.system.sem
            waiting = sem.locked()
            if waiting:
                await activity.record(self.system.s, "worker.slot.wait", level="warning", actor_id=self.actor_id,
                                      summary=f"all {self.system.max_concurrent} run slots are busy; waiting for one",
                                      max_concurrent_runs=self.system.max_concurrent)
            t0 = time.monotonic()
            async with sem:
                if waiting:
                    await activity.record(self.system.s, "worker.slot.acquired", actor_id=self.actor_id,
                                          summary=f"got a run slot after {time.monotonic() - t0:.1f}s",
                                          waited_seconds=round(time.monotonic() - t0, 3))
                batch = await self._pick()
                if batch is None:
                    return
                self.drained += 1
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
                # Everything queued is mail for threads parked on a question this bot asked: nothing can
                # run until someone answers. The most common reason a thread "does nothing".
                await activity.record(s, "worker.parked", session=session, level="warning", actor_id=self.actor_id,
                                      summary=f"{len(items)} queued item(s) all belong to {len(parked)} thread(s) parked on a "
                                              f"question; nothing to run until it is answered",
                                      queued=len(items), queued_item_ids=[i.id for i in items],
                                      thread_ids=sorted({i.thread_id for i in items}), parked_thread_ids=sorted(parked))
                await session.commit()
                return None
            if chosen.kind == "resume":
                chosen.status = "processing"
                await activity.record(s, "resume.picked", session=session, thread_id=chosen.thread_id, actor_id=self.actor_id,
                                      run_id=chosen.run_id, item_id=chosen.id,
                                      summary=f"picked the answer from @{chosen.payload.get('from') or '?'}; resuming the run",
                                      queued=len(items), skipped_parked=len(parked))
                await session.commit()
                return Batch(run_id=chosen.run_id, items=[chosen], resume=chosen.payload.get("resume"))
            group = [i for i in items if i.kind == "message" and i.thread_id == chosen.thread_id]
            run = Run(actor_id=self.actor_id, thread_id=chosen.thread_id, status="queued")
            session.add(run)
            await session.flush()
            for i in group:
                i.status, i.run_id = "processing", run.id
            await activity.record(s, "run.created", session=session, thread_id=run.thread_id, actor_id=self.actor_id, run_id=run.id,
                                  summary=f"picked {len(group)} item(s) into a new run; {len(items) - len(group)} left queued",
                                  item_ids=[i.id for i in group], message_ids=[i.message_id for i in group],
                                  queued_before=len(items), left_queued=len(items) - len(group),
                                  other_threads_queued=sorted({i.thread_id for i in items if i.thread_id != run.thread_id}),
                                  parked_thread_ids=sorted(parked))
            await session.commit()
            await s.bus.publish("run.updated", run.thread_id, to_json(RunOut, run))
            await s.bus.publish("bots.updated", None, {"id": run.actor_id, "active": True})
            # The items are "processing" now: this thread no longer waits for this bot, and the
            # thread window should say so the moment the run starts, not when it finishes.
            await publish_waiters(s, session, run.thread_id)
            return Batch(run_id=run.id, items=group)

    async def _process(self, batch: Batch) -> None:
        s = self.system.s
        cmd = Command(resume=batch.resume) if batch.resume is not None else None
        thread_id = batch.items[0].thread_id if batch.items else None
        self.current_run_id = batch.run_id
        await activity.record(s, "run.dispatched", thread_id=thread_id, actor_id=self.actor_id, run_id=batch.run_id,
                              summary="handed to the runner" + (" (resume)" if batch.resume is not None else ""),
                              resume=batch.resume is not None, item_ids=[i.id for i in batch.items])
        started = time.monotonic()
        self.current_task = asyncio.create_task(s.runner.execute(batch.run_id, resume=cmd))
        status = "done"
        crash: str | None = None
        try:
            await self.current_task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            status = "cancelled"
        except Exception as e:
            log.exception("run %s crashed", batch.run_id)
            crash = f"{type(e).__name__}: {e}"[:2000]
        finally:
            self.current_task, self.current_run_id = None, None
            await activity.record(s, "run.finished", level="error" if crash else "info", thread_id=thread_id,
                                  actor_id=self.actor_id, run_id=batch.run_id,
                                  summary=f"runner returned after {time.monotonic() - started:.1f}s; settling items as {status}"
                                          + (f"; runner crashed: {crash}" if crash else ""),
                                  status=status, seconds=round(time.monotonic() - started, 3), crash=crash)
            rows: list[InboxItem] = []
            try:
                async with s.session_factory() as session:
                    # Only items still "processing": a cancel_run that raced _pick already settled
                    # them as "cancelled", and that must not be overwritten with "done".
                    rows = (await session.execute(select(InboxItem).where(InboxItem.id.in_([i.id for i in batch.items]),
                                                                          InboxItem.status == "processing"))).scalars().all()
                    for i in rows:
                        i.status, i.processed_at = status, utcnow()
                    await activity.record(s, "inbox.settled", session=session, thread_id=thread_id, actor_id=self.actor_id,
                                          run_id=batch.run_id, summary=f"{len(rows)} item(s) marked {status}",
                                          status=status, item_ids=[i.id for i in rows],
                                          already_settled=[i.id for i in batch.items if i.id not in {r.id for r in rows}])
                    await session.commit()
                for i in rows:
                    await s.bus.publish("inbox.updated", i.thread_id, to_json(InboxItemOut, i))
            except Exception:
                # Best-effort: bookkeeping must never abort the drain or mask the run's own error.
                # Items left "processing" are requeued by recovery on the next start().
                log.exception("failed to finalize inbox items for run %s", batch.run_id)
            if thread_id is not None:
                await self._release_held_handoffs(thread_id)

    async def _release_held_handoffs(self, thread_id: str) -> None:
        """Deliver a hand-off this bot held in `thread_id` (see delivery.post_message) now that its own
        queue there is empty, so the model never has to remember to re-mention the bot it held.

        Held requests from this bot are grouped by target handle, keeping only the latest per target
        (an older hold to the same target is superseded by a newer one and dropped). A hold is skipped,
        not delivered, if a later reply from this bot already produced a real InboxItem for that target
        (a fresh, unheld mention, or an earlier run of this same method) -- so this never double-wakes
        anyone. What ships is the held message itself, unmodified: by the time the target's run reads
        it, the rest of the thread (including whatever this bot said since) is visible too."""
        s = self.system.s
        try:
            async with s.session_factory() as session:
                still_queued = (await session.execute(select(InboxItem.id).where(
                    InboxItem.actor_id == self.actor_id, InboxItem.thread_id == thread_id,
                    InboxItem.kind == "message", InboxItem.status == "queued").limit(1))).first()
                if still_queued is not None:
                    return
                held_msgs = (await session.execute(
                    select(Message).where(Message.thread_id == thread_id, Message.sender_actor_id == self.actor_id)
                    .order_by(Message.created_at, Message.id))).scalars().all()
                by_target: dict[str, Message] = {}
                for m in held_msgs:
                    for handle in m.meta.get("held_handoff") or []:
                        by_target[handle] = m         # chronological order: last write per handle wins
                if not by_target:
                    return
                bots_by_handle = {a.handle: a for a in (await session.execute(select(Actor).where(Actor.kind == "bot"))).scalars()}
                part_ids = {p.actor_id for p in (await session.execute(
                    select(ThreadParticipant).where(ThreadParticipant.thread_id == thread_id))).scalars()}
                released: list[InboxItem] = []
                for handle, hm in by_target.items():
                    target = bots_by_handle.get(handle)
                    if target is None:
                        continue
                    covered = (await session.execute(
                        select(InboxItem.id).join(Message, Message.id == InboxItem.message_id)
                        .where(InboxItem.actor_id == target.id, InboxItem.thread_id == thread_id, InboxItem.kind == "message",
                              Message.sender_actor_id == self.actor_id, Message.created_at >= hm.created_at)
                        .limit(1))).first()
                    if covered is not None:
                        continue        # a later reply already reached it for real, or this hold was already delivered
                    if target.id not in part_ids:
                        session.add(ThreadParticipant(thread_id=thread_id, actor_id=target.id))
                        part_ids.add(target.id)
                    item = InboxItem(actor_id=target.id, thread_id=thread_id, kind="message", message_id=hm.id)
                    session.add(item)
                    released.append(item)
                if not released:
                    return
                await session.flush()
                me = await session.get(Actor, self.actor_id)
                handle_by_target_id = {t.id: h for h, t in bots_by_handle.items()}
                for item in released:
                    handle = handle_by_target_id[item.actor_id]
                    hm = by_target[handle]
                    await activity.record(s, "inbox.hold_released", session=session, thread_id=thread_id, actor_id=item.actor_id,
                                          item_id=item.id, message_id=item.message_id,
                                          summary=f"delivered the hand-off @{me.handle if me else self.actor_id} held for "
                                                  f"@{handle}: its queue in this thread is now empty",
                                          held_by=me.handle if me else self.actor_id, target=handle,
                                          held_since=hm.created_at.isoformat())
                await session.commit()
                await publish_waiters(s, session, thread_id)
            for item in released:
                await s.bus.publish("inbox.updated", item.thread_id, to_json(InboxItemOut, item))
            for item in released:
                await self.system.notify(item.actor_id, thread_id=thread_id)
        except Exception:
            log.exception("could not release held hand-offs for actor %s thread %s", self.actor_id, thread_id)


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
            await activity.record(self.system.s, "inbox.picked", session=session, thread_id=item.thread_id, actor_id=self.actor_id,
                                  item_id=item.id, message_id=item.message_id, run_id=item.run_id,
                                  summary=f"picked {item.kind} item for webhook delivery", kind=item.kind)
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
            await activity.record(s, "webhook.attempt", level="info" if ok else "warning", thread_id=item.thread_id,
                                  actor_id=self.actor_id, item_id=item.id, run_id=item.run_id,
                                  summary=f"webhook attempt {attempt}/{len(delays)}: {'ok' if ok else last_error}",
                                  attempt=attempt, of=len(delays), ok=ok, error=last_error)
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
                await activity.record(s, "inbox.settled", session=session, level="error" if status == "failed" else "info",
                                      thread_id=it.thread_id, actor_id=self.actor_id, item_id=it.id, run_id=it.run_id,
                                      summary=f"webhook item marked {status} after {attempts} attempt(s)"
                                              + (f": {error}" if error else ""),
                                      status=status, item_ids=[it.id], attempts=attempts, error=error)
            await session.commit()
        if status in ("done", "failed"):
            await s.bus.publish("inbox.updated", it.thread_id, to_json(InboxItemOut, it))


class ActorSystem:
    def __init__(self, services, max_concurrent: int) -> None:
        self.s = services
        self.max_concurrent = max_concurrent
        self.sem = asyncio.Semaphore(max_concurrent)
        self._workers: dict[str, _Worker] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        interrupted: list[tuple[str, str]] = []
        async with self.s.session_factory() as session:
            # "queued" runs are orphans too: _pick commits the Run row and flips its items to
            # "processing" before the semaphore and the runner, so a shutdown in that window leaves a
            # run nothing will ever pick up (it blocks DELETE /bots/{id} and draws a phantom active
            # card). No worker exists yet at this point in start(), so every queued run is provably
            # stale and gets the same treatment as an interrupted running one.
            stale = select(Run).where(Run.status.in_(["running", "queued"]))
            failed_ids: list[str] = []
            for run in (await session.execute(stale)).scalars():
                was = run.status
                run.status, run.error, run.finished_at = "failed", "server restarted", utcnow()
                failed_ids.append(run.id)
                bot = await session.get(Actor, run.actor_id)
                interrupted.append((run.thread_id, bot.handle if bot else "bot"))
                settled = []
                for it in (await session.execute(select(InboxItem).where(InboxItem.run_id == run.id, InboxItem.status == "processing"))).scalars():
                    it.status, it.processed_at = "done", utcnow()
                    settled.append(it.id)
                await activity.record(self.s, "recovery.run_failed", session=session, level="warning", thread_id=run.thread_id,
                                      actor_id=run.actor_id, run_id=run.id,
                                      summary=f"run was {was} at the last shutdown; marked failed, {len(settled)} item(s) settled",
                                      previous_status=was, item_ids=settled)
            requeued = []
            for it in (await session.execute(select(InboxItem).where(InboxItem.status == "processing"))).scalars():
                it.status = "queued"
                requeued.append(it.id)
            if requeued:
                await activity.record(self.s, "recovery.items_requeued", session=session, level="warning",
                                      summary=f"{len(requeued)} item(s) were processing at the last shutdown; requeued",
                                      item_ids=requeued)
            await session.commit()
            pending = (await session.execute(select(InboxItem.actor_id).where(InboxItem.status == "queued").distinct())).scalars().all()
        await activity.record(self.s, "system.started",
                              summary=f"actor system started: {len(failed_ids)} interrupted run(s), {len(pending)} actor(s) with queued mail",
                              interrupted_runs=failed_ids, pending_actor_ids=list(pending), max_concurrent_runs=self.max_concurrent)
        for run_id in failed_ids:
            await self._drop_checkpoint(run_id)
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
        await refresh_waiters_at_start(self.s)

    async def stop(self) -> None:
        self._started = False
        workers, self._workers = list(self._workers.values()), {}
        for w in workers:
            await w.stop()

    async def notify(self, actor_id: str, thread_id: str | None = None) -> None:
        if not self._started:
            return
        w = self._workers.get(actor_id)
        created = False
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
                created = True
        busy, already = w.busy, w._wake.is_set()
        w.wake()
        state = ("started" if created else "already busy; will re-check its inbox when done" if busy
                 else "already awake" if already else "woken")
        await activity.record(self.s, "worker.notified", level="debug", thread_id=thread_id, actor_id=actor_id,
                              summary=f"worker {state}", worker_created=created, busy=busy, already_awake=already,
                              current_run_id=getattr(w, "current_run_id", None))

    async def cancel_run(self, run_id: str) -> bool:
        async with self.s.session_factory() as session:
            run = await session.get(Run, run_id)
        if run is None:
            return False
        for w in self._workers.values():
            if isinstance(w, BotActor) and w.current_run_id == run_id and w.current_task:
                await activity.record(self.s, "run.cancel_requested", level="warning", thread_id=run.thread_id,
                                      actor_id=run.actor_id, run_id=run_id, summary="cancelling the live run", live=True)
                w.current_task.cancel()
                return True
        async with self.s.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None or run.status not in ("queued", "waiting_human"):
                return False
            was = run.status
            run.status, run.finished_at = "cancelled", utcnow()
            items = (await session.execute(select(InboxItem).where(InboxItem.run_id == run_id, InboxItem.status.in_(["queued", "processing"])))).scalars().all()
            for i in items:
                i.status, i.processed_at = "cancelled", utcnow()
            await activity.record(self.s, "run.cancel_requested", session=session, level="warning", thread_id=run.thread_id,
                                  actor_id=run.actor_id, run_id=run_id,
                                  summary=f"cancelled the {was} run; {len(items)} item(s) cancelled",
                                  live=False, previous_status=was, item_ids=[i.id for i in items])
            # A live run's status changes go through the runner; this one ends here, so say so the same way.
            await activity.record(self.s, "run.status", session=session, thread_id=run.thread_id, actor_id=run.actor_id,
                                  run_id=run_id, summary="run cancelled", status="cancelled", error=None,
                                  interrupt_kind=None, usage=None, langsmith_run_id=None)
            await session.commit()
            await self.s.bus.publish("run.updated", run.thread_id, to_json(RunOut, run))
            await self.s.bus.publish("bots.updated", None, {"id": run.actor_id, "active": False})
            await publish_waiters(self.s, session, run.thread_id)
        await self._drop_checkpoint(run_id)
        await self.notify(run.actor_id, thread_id=run.thread_id)     # parked thread may now have waiting mail
        return True

    async def purge(self, actor_id: str) -> dict[str, int]:
        """Stop everything a bot is doing and is about to do: every queued inbox item is cancelled first
        (so the worker finds nothing to pick next), then every open run (queued, waiting on a question,
        or live). Waits for a live run to actually end, bounded, so the caller sees the settled state.
        Returns the counts; a bot with nothing going on gives zeros."""
        async with self.s.session_factory() as session:
            queued = (await session.execute(select(InboxItem).where(InboxItem.actor_id == actor_id, InboxItem.status == "queued"))).scalars().all()
            for i in queued:
                i.status, i.processed_at = "cancelled", utcnow()
            open_runs = (await session.execute(select(Run).where(Run.actor_id == actor_id, Run.status.in_(OPEN_RUN_STATUSES)))).scalars().all()
            await activity.record(self.s, "inbox.purged", session=session, level="warning", actor_id=actor_id,
                                  summary=f"operator purged the inbox: {len(queued)} queued item(s) cancelled, "
                                          f"{len(open_runs)} open run(s) to cancel",
                                  purged=len(queued), item_ids=[i.id for i in queued], thread_ids=sorted({i.thread_id for i in queued}),
                                  run_ids=[r.id for r in open_runs], run_statuses={r.id: r.status for r in open_runs})
            await session.commit()
        for i in queued:
            await self.s.bus.publish("inbox.updated", i.thread_id, to_json(InboxItemOut, i))
        cancelled, live = 0, []
        for run in open_runs:
            w = self._workers.get(actor_id)
            task = w.current_task if isinstance(w, BotActor) and w.current_run_id == run.id else None
            if await self.cancel_run(run.id):
                cancelled += 1
                if task is not None:
                    live.append(task)
        if live:
            await asyncio.wait(live, timeout=10)
        async with self.s.session_factory() as session:
            for thread_id in sorted({i.thread_id for i in queued}):
                await publish_waiters(self.s, session, thread_id)
        await self.s.bus.publish("bots.updated", None, {"id": actor_id, "active": False})
        return {"cancelled_runs": cancelled, "purged_items": len(queued)}

    async def _drop_checkpoint(self, run_id: str) -> None:
        """A run that ends outside the runner (cancelled while waiting, or failed by a restart) still
        owns a checkpoint nobody will read again."""
        try:
            await self.s.checkpointer.adelete_thread(run_id)
        except Exception:
            log.exception("could not delete the checkpoint for run %s", run_id)

    async def enqueue_resume(self, run: Run, value, from_actor: Actor | None) -> InboxItem:
        async with self.s.session_factory() as session:
            item = InboxItem(actor_id=run.actor_id, thread_id=run.thread_id, kind="resume", run_id=run.id,
                             payload={"resume": value, "from": from_actor.handle if from_actor else None})
            session.add(item)
            await session.flush()
            await activity.record(self.s, "inbox.enqueued", session=session, thread_id=run.thread_id, actor_id=run.actor_id,
                                  run_id=run.id, item_id=item.id,
                                  summary=f"queued resume from @{from_actor.handle if from_actor else '?'} for the waiting run",
                                  kind="resume", value=activity.preview(value))
            await session.commit()
        await self.s.bus.publish("inbox.updated", item.thread_id, to_json(InboxItemOut, item))
        await self.notify(run.actor_id, thread_id=run.thread_id)
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
