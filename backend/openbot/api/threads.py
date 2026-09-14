from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.deps import get_services, get_session
from openbot.api.schemas import (
    MessageOut,
    ParticipantOut,
    RunOut,
    ThreadCreate,
    ThreadDetail,
    ThreadOut,
)
from openbot.db.models import (
    OPEN_RUN_STATUSES,
    Actor,
    InboxItem,
    Message,
    Run,
    Thread,
    ThreadParticipant,
)
from openbot.runtime.delivery import ack_items, create_thread, human_actor
from openbot.services import Services

router = APIRouter(prefix="/threads", tags=["threads"])


async def participants_for(session: AsyncSession, thread_ids: list[str]) -> dict[str, list[ParticipantOut]]:
    out: dict[str, list[ParticipantOut]] = {t: [] for t in thread_ids}
    if not thread_ids:
        return out
    rows = (await session.execute(select(ThreadParticipant, Actor).join(Actor, Actor.id == ThreadParticipant.actor_id)
                                  .where(ThreadParticipant.thread_id.in_(thread_ids)))).all()
    for p, a in rows:
        out[p.thread_id].append(ParticipantOut(actor_id=a.id, kind=a.kind, handle=a.handle, name=a.name))
    return out


def thread_out(thread: Thread, parts: list[ParticipantOut]) -> ThreadOut:
    t = ThreadOut.model_validate(thread)
    t.participants = parts
    return t


async def get_thread_or_404(session: AsyncSession, thread_id: str) -> Thread:
    thread = await session.get(Thread, thread_id)
    if not thread:
        raise HTTPException(404, "thread not found")
    return thread


@router.get("", response_model=list[ThreadOut])
async def list_threads(session: AsyncSession = Depends(get_session)):
    threads = (await session.execute(select(Thread).order_by(Thread.updated_at.desc()))).scalars().all()
    parts = await participants_for(session, [t.id for t in threads])
    return [thread_out(t, parts[t.id]) for t in threads]


@router.post("", response_model=ThreadOut, status_code=201)
async def create(body: ThreadCreate, session: AsyncSession = Depends(get_session), services: Services = Depends(get_services)):
    you = await human_actor(session)
    try:
        thread = await create_thread(services, session, title=body.title, handles=body.handles, created_by=you)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    parts = await participants_for(session, [thread.id])
    return thread_out(thread, parts[thread.id])


@router.get("/{thread_id}", response_model=ThreadDetail)
async def get_thread(thread_id: str, before: str | None = None, limit: int = 50, session: AsyncSession = Depends(get_session)):
    thread = await get_thread_or_404(session, thread_id)
    q = select(Message).where(Message.thread_id == thread_id)
    if before and (anchor := await session.get(Message, before)):
        q = q.where(Message.created_at < anchor.created_at)
    rows = (await session.execute(q.order_by(Message.created_at.desc()).limit(limit + 1))).scalars().all()
    runs = (await session.execute(select(Run).where(Run.thread_id == thread_id, Run.status.in_(OPEN_RUN_STATUSES))
                                  .order_by(Run.created_at))).scalars().all()
    parts = await participants_for(session, [thread_id])
    d = ThreadDetail.model_validate(thread)
    d.participants = parts[thread_id]
    d.messages = [MessageOut.model_validate(m) for m in reversed(rows[:limit])]
    d.has_more = len(rows) > limit
    d.runs = [RunOut.model_validate(r) for r in runs]
    return d


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
