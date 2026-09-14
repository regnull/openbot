from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.deps import get_services, get_session
from openbot.api.messages import resolve_sender
from openbot.api.schemas import (
    ActorCreate,
    ActorMessageCreate,
    ActorMessageOut,
    ActorOut,
    ActorUpdate,
    MessageOut,
    actor_out,
)
from openbot.api.threads import participants_for, thread_out
from openbot.db.models import Actor, ExternalProfile, Thread
from openbot.runtime.delivery import actor_by_handle, create_thread, post_message
from openbot.services import Services

router = APIRouter(prefix="/actors", tags=["actors"])


async def get_actor_or_404(session: AsyncSession, actor_id: str) -> Actor:
    actor = await session.get(Actor, actor_id)
    if not actor:
        raise HTTPException(404, "actor not found")
    return actor


async def handle_taken(session: AsyncSession, handle: str) -> bool:
    return (await session.execute(select(Actor.id).where(Actor.handle == handle))).first() is not None


@router.get("", response_model=list[ActorOut])
async def list_actors(session: AsyncSession = Depends(get_session)):
    actors = (await session.execute(select(Actor).order_by(Actor.kind, Actor.handle))).scalars().all()
    return [actor_out(a) for a in actors]


@router.post("", response_model=ActorOut, status_code=201)
async def create_external(body: ActorCreate, session: AsyncSession = Depends(get_session)):
    if await handle_taken(session, body.handle):
        raise HTTPException(409, "handle already exists")
    actor = Actor(kind="external", handle=body.handle, name=body.name, description=body.description,
                  external=ExternalProfile(webhook_url=body.webhook_url, webhook_secret=body.webhook_secret))
    session.add(actor)
    await session.commit()
    return actor_out(actor)


@router.get("/{actor_id}", response_model=ActorOut)
async def get_actor(actor_id: str, session: AsyncSession = Depends(get_session)):
    return actor_out(await get_actor_or_404(session, actor_id))


@router.patch("/{actor_id}", response_model=ActorOut)
async def update_actor(actor_id: str, body: ActorUpdate, session: AsyncSession = Depends(get_session)):
    actor = await get_actor_or_404(session, actor_id)
    if actor.kind != "external":
        raise HTTPException(409, "only external actors can be edited here; use /bots for bots")
    data = body.model_dump(exclude_unset=True)
    for k in ("name", "description", "enabled"):
        if k in data:
            setattr(actor, k, data[k])
    for k in ("webhook_url", "webhook_secret"):
        if k in data:
            setattr(actor.external, k, data[k])
    await session.commit()
    return actor_out(actor)


@router.delete("/{actor_id}", status_code=204)
async def delete_actor(actor_id: str, session: AsyncSession = Depends(get_session)):
    actor = await get_actor_or_404(session, actor_id)
    if actor.kind != "external":
        raise HTTPException(409, "only external actors can be deleted here")
    await session.delete(actor)
    await session.commit()


@router.post("/{handle}/messages", response_model=ActorMessageOut, status_code=201)
async def message_actor(handle: str, body: ActorMessageCreate, session: AsyncSession = Depends(get_session),
                        services: Services = Depends(get_services)):
    target = await actor_by_handle(session, handle)
    if target is None:
        raise HTTPException(404, "actor not found")
    sender = await resolve_sender(session, body.from_handle)
    thread = None
    if body.thread_id:
        thread = await session.get(Thread, body.thread_id)
        if thread is None:
            raise HTTPException(404, "thread not found")
    elif body.external_ref:
        thread = (await session.execute(select(Thread).where(Thread.external_ref == body.external_ref))).scalar_one_or_none()
    if thread is None:
        thread = await create_thread(services, session, title=f"{sender.name} ↔ {target.name}", handles=[handle],
                                     created_by=sender, external_ref=body.external_ref)
    try:
        res = await post_message(services, session, thread_id=thread.id, sender=sender, content=body.content, to_handles=[handle])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    parts = await participants_for(session, [thread.id])
    return ActorMessageOut(thread=thread_out(thread, parts[thread.id]), message=MessageOut.model_validate(res.message),
                           addressed=[a.handle for a in res.addressed])
