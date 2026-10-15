"""Bot waiting-state for the thread window.

A thread "waits" for a bot between the moment a message mentioning it is delivered (its inbox items
are `queued`) and the moment an actor worker picks those items up (they become `processing`). The
state is never stored: it is derived from the inbox queue itself, so it cannot drift from what the
workers actually see, and it costs no schema migration.

`publish_waiters` is called at every transition (delivery, pickup, ack, restart recovery) and
broadcasts the full waiter list for one thread as a `waiters.updated` bus event, which drives both
the SSE stream and the thread window. `GET /threads/{id}` computes the same list so a freshly opened
page is correct without an event replay.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.schemas import WaiterOut
from openbot.db.models import Actor, InboxItem

log = logging.getLogger(__name__)

# Only bots wait visibly in the thread window. External actors answer over webhooks and the human's
# "queued" inbox items are just unread mail, not a busy-bot signal.
WAITER_KINDS = ("bot",)


async def waiters_for(session: AsyncSession, thread_id: str) -> list[WaiterOut]:
    """Bots with queued, unpicked `message` items in this thread, in queue order.

    A bot's inbox is one FIFO across threads, so the honest position to show is where this thread's
    first queued item sits inside that FIFO — a bot busy in another thread shows "position 2" here
    when one item is ahead of it, wherever that earlier item came from.
    """
    grouped = (await session.execute(
        select(InboxItem.actor_id, Actor.handle, Actor.name,
               func.count().label("count"), func.min(InboxItem.created_at).label("first"))
        .join(Actor, Actor.id == InboxItem.actor_id)
        .where(InboxItem.thread_id == thread_id, InboxItem.status == "queued", InboxItem.kind == "message",
               Actor.kind.in_(WAITER_KINDS))
        .group_by(InboxItem.actor_id, Actor.handle, Actor.name)
        .order_by("first")
    )).all()
    if not grouped:
        return []
    firsts = {actor_id: first for actor_id, _handle, _name, _count, first in grouped}
    # Walk every bot's cross-thread FIFO once: position = 1 + items queued earlier than this
    # thread's first item; queue_len = everything the bot still has queued, any thread.
    position: dict[str, int] = dict.fromkeys(firsts, 0)
    total: dict[str, int] = dict.fromkeys(firsts, 0)
    for actor_id, created in (await session.execute(
            select(InboxItem.actor_id, InboxItem.created_at)
            .where(InboxItem.actor_id.in_(firsts), InboxItem.status == "queued", InboxItem.kind == "message")
            .order_by(InboxItem.actor_id, InboxItem.created_at))).all():
        total[actor_id] += 1
        if created < firsts[actor_id]:
            position[actor_id] += 1
    return [WaiterOut(actor_id=actor_id, handle=handle, name=name, count=count,
                      position=position[actor_id] + 1, queue_len=total[actor_id])
            for actor_id, handle, name, count, _first in grouped]


async def publish_waiters(services, session: AsyncSession, thread_id: str) -> list[WaiterOut]:
    """Compute the thread's waiter list and broadcast it.

    The payload is shaped {waiters: [...]} rather than bare so future fields can be added without a
    breaking change for SSE consumers. Returns the list for callers that also serve it over HTTP, so
    the two can never disagree about ordering or content.
    """
    waiters = await waiters_for(session, thread_id)
    await services.bus.publish("waiters.updated", thread_id, {"waiters": [w.model_dump() for w in waiters]})
    return waiters


async def refresh_waiters_at_start(services) -> None:
    """Re-broadcast the waiter list for every thread that has one.

    A restart requeues orphaned items without anyone re-delivering a message, and events published
    while a subscriber was disconnected are never replayed, so a listener that connects after the
    facts would otherwise keep showing a stale waiting state.
    """
    try:
        async with services.session_factory() as session:
            ids = (await session.execute(
                select(InboxItem.thread_id).join(Actor, Actor.id == InboxItem.actor_id)
                .where(InboxItem.status == "queued", InboxItem.kind == "message", Actor.kind.in_(WAITER_KINDS))
                .distinct())).scalars().all()
            for thread_id in ids:
                await publish_waiters(services, session, thread_id)
    except Exception:
        # Waiter events are cosmetic; a failure here must never keep the actor system from starting.
        log.exception("could not refresh waiters on start")
