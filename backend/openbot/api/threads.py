from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.deps import get_services, get_session
from openbot.api.schemas import (
    MessageOut,
    ParticipantOut,
    RunOut,
    ThreadCreate,
    ThreadDetail,
    ThreadOut,
    ThreadUpdate,
    ThreadUsage,
)
from openbot.db.models import (
    ACTIVE_RUN_STATUSES,
    Actor,
    InboxItem,
    Message,
    Run,
    Thread,
    ThreadParticipant,
)
from openbot.runtime.delivery import (
    DEFAULT_BOT_HANDLE,
    ack_items,
    actor_by_handle,
    create_thread,
    human_actor,
)
from openbot.runtime.waiters import waiters_for
from openbot.services import Services

router = APIRouter(prefix="/threads", tags=["threads"])


async def default_bot_handles_for(session: AsyncSession, thread_ids: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {t: None for t in thread_ids}
    if not thread_ids:
        return out
    rows = (await session.execute(select(Thread.id, Actor.handle).join(Actor, Actor.id == Thread.default_bot_actor_id)
                                  .where(Thread.id.in_(thread_ids)))).all()
    for thread_id, handle in rows:
        out[thread_id] = handle
    if any(handle is None for handle in out.values()) and await actor_by_handle(session, DEFAULT_BOT_HANDLE):
        out = {thread_id: handle or DEFAULT_BOT_HANDLE for thread_id, handle in out.items()}
    return out


async def participants_for(session: AsyncSession, thread_ids: list[str]) -> dict[str, list[ParticipantOut]]:
    out: dict[str, list[ParticipantOut]] = {t: [] for t in thread_ids}
    if not thread_ids:
        return out
    rows = (await session.execute(select(ThreadParticipant, Actor).join(Actor, Actor.id == ThreadParticipant.actor_id)
                                  .where(ThreadParticipant.thread_id.in_(thread_ids)))).all()
    for p, a in rows:
        out[p.thread_id].append(ParticipantOut(actor_id=a.id, kind=a.kind, handle=a.handle, name=a.name))
    return out


async def thread_out(session: AsyncSession, thread: Thread, parts: list[ParticipantOut], default_bot_handle: str | None) -> ThreadOut:
    t = ThreadOut.model_validate(thread)
    t.default_bot_handle = default_bot_handle
    t.participants = parts
    t.active = (await session.execute(select(Run.id).where(Run.thread_id == thread.id, Run.status.in_(ACTIVE_RUN_STATUSES)).limit(1))).first() is not None
    return t


async def get_thread_or_404(session: AsyncSession, thread_id: str) -> Thread:
    thread = await session.get(Thread, thread_id)
    if not thread:
        raise HTTPException(404, "thread not found")
    return thread


@router.get("", response_model=list[ThreadOut])
async def list_threads(session: AsyncSession = Depends(get_session)):
    threads = (await session.execute(select(Thread).where(Thread.kind == "chat").order_by(Thread.updated_at.desc()))).scalars().all()
    ids = [t.id for t in threads]
    parts = await participants_for(session, ids)
    default_handles = await default_bot_handles_for(session, ids)
    return [await thread_out(session, t, parts[t.id], default_handles[t.id]) for t in threads]


@router.post("", response_model=ThreadOut, status_code=201)
async def create(body: ThreadCreate, session: AsyncSession = Depends(get_session), services: Services = Depends(get_services)):
    you = await human_actor(session)
    try:
        thread = await create_thread(services, session, title=body.title, handles=body.handles, created_by=you,
                                     default_bot_handle=body.default_bot_handle,
                                     working_directory=body.working_directory)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    parts = await participants_for(session, [thread.id])
    default_handles = await default_bot_handles_for(session, [thread.id])
    return await thread_out(session, thread, parts[thread.id], default_handles[thread.id])


@router.get("/{thread_id}", response_model=ThreadDetail)
async def get_thread(thread_id: str, before: str | None = None, limit: int = Query(50, ge=1, le=200),
                     session: AsyncSession = Depends(get_session)):
    thread = await get_thread_or_404(session, thread_id)
    q = select(Message).where(Message.thread_id == thread_id)
    if before and (anchor := await session.get(Message, before)):
        q = q.where(Message.created_at < anchor.created_at)
    rows = (await session.execute(q.order_by(Message.created_at.desc()).limit(limit + 1))).scalars().all()
    runs = (await session.execute(select(Run).where(Run.thread_id == thread_id, Run.status.in_(ACTIVE_RUN_STATUSES))
                                  .order_by(Run.created_at))).scalars().all()
    parts = await participants_for(session, [thread_id])
    default_handles = await default_bot_handles_for(session, [thread_id])
    d = ThreadDetail.model_validate(thread)
    d.default_bot_handle = default_handles[thread_id]
    d.participants = parts[thread_id]
    d.messages = [MessageOut.model_validate(m) for m in reversed(rows[:limit])]
    d.has_more = len(rows) > limit
    d.runs = [RunOut.model_validate(r) for r in runs]
    d.active = bool(runs)
    # Waiting bots are computed from the inbox queue, not stored, so a freshly opened page is right
    # even if every waiters.updated event was published before the SSE socket existed.
    d.waiters = await waiters_for(session, thread_id)
    return d


@router.get("/{thread_id}/usage", response_model=ThreadUsage)
async def get_thread_usage(thread_id: str, session: AsyncSession = Depends(get_session)):
    """Sum usage over all runs in the thread; runs that never reported usage count as zero."""
    await get_thread_or_404(session, thread_id)
    cols = [func.coalesce(func.sum(getattr(Run, k)), 0) for k in ThreadUsage.model_fields]
    row = (await session.execute(select(*cols).where(Run.thread_id == thread_id))).one()
    return ThreadUsage(**dict(zip(ThreadUsage.model_fields, row, strict=True)))


@router.patch("/{thread_id}", response_model=ThreadOut)
async def update_thread(thread_id: str, body: ThreadUpdate, session: AsyncSession = Depends(get_session)):
    thread = await get_thread_or_404(session, thread_id)
    bot = await actor_by_handle(session, body.default_bot_handle)
    if bot is None:
        raise HTTPException(422, f"unknown default bot: {body.default_bot_handle}")
    if bot.kind != "bot":
        raise HTTPException(422, f"default bot must be a bot: {body.default_bot_handle}")
    thread.default_bot_actor_id = bot.id
    existing = (await session.execute(select(ThreadParticipant).where(
        ThreadParticipant.thread_id == thread_id, ThreadParticipant.actor_id == bot.id))).scalar_one_or_none()
    if existing is None:
        session.add(ThreadParticipant(thread_id=thread_id, actor_id=bot.id))
    await session.commit()
    parts = await participants_for(session, [thread_id])
    return await thread_out(session, thread, parts[thread_id], bot.handle)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, session: AsyncSession = Depends(get_session)):
    thread = await get_thread_or_404(session, thread_id)
    for model in (InboxItem, Run, Message, ThreadParticipant):
        for row in (await session.execute(select(model).where(model.thread_id == thread_id))).scalars():
            await session.delete(row)
    await session.flush()  # remove children before the parent, or the DB cascade beats the ORM to them
    await session.delete(thread)
    await session.commit()


@router.post("/{thread_id}/ack")
async def ack_thread(thread_id: str, session: AsyncSession = Depends(get_session), services: Services = Depends(get_services)):
    await get_thread_or_404(session, thread_id)
    you = await human_actor(session)
    items = list((await session.execute(select(InboxItem).where(
        InboxItem.actor_id == you.id, InboxItem.thread_id == thread_id, InboxItem.kind == "message",
        InboxItem.status == "queued"))).scalars().all())
    await ack_items(services, session, items)
    return {"acked": len(items)}
