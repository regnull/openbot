from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.deps import get_services, get_session
from openbot.api.schemas import InboxItemOut, MessageOut
from openbot.db.models import Actor, InboxItem, Message
from openbot.runtime.delivery import ack_items, actor_by_handle, human_actor
from openbot.services import Services

router = APIRouter(tags=["inbox"])


async def inbox_for(session: AsyncSession, actor: Actor, status: str | None, limit: int = 200) -> list[InboxItemOut]:
    q = select(InboxItem).where(InboxItem.actor_id == actor.id)
    if status:
        q = q.where(InboxItem.status == status)
    items = (await session.execute(q.order_by(InboxItem.created_at.desc()).limit(limit))).scalars().all()
    msg_ids = [i.message_id for i in items if i.message_id]
    msgs = {m.id: m for m in (await session.execute(select(Message).where(Message.id.in_(msg_ids)))).scalars()} if msg_ids else {}
    out = []
    for it in items:
        o = InboxItemOut.model_validate(it)
        o.message = MessageOut.model_validate(msgs[it.message_id]) if it.message_id in msgs else None
        out.append(o)
    return out


@router.get("/inbox", response_model=list[InboxItemOut])
async def my_inbox(status: str | None = "queued", limit: int = Query(200, ge=1, le=200),
                   session: AsyncSession = Depends(get_session)):
    return await inbox_for(session, await human_actor(session), status, limit)


@router.get("/actors/{handle}/inbox", response_model=list[InboxItemOut])
async def actor_inbox(handle: str, status: str | None = "queued", limit: int = Query(200, ge=1, le=200),
                      session: AsyncSession = Depends(get_session)):
    actor = await actor_by_handle(session, handle)
    if actor is None:
        raise HTTPException(404, "actor not found")
    return await inbox_for(session, actor, status, limit)


@router.post("/inbox/{item_id}/ack", response_model=InboxItemOut)
async def ack(item_id: str, session: AsyncSession = Depends(get_session), services: Services = Depends(get_services)):
    item = await session.get(InboxItem, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if item.status == "queued":
        await ack_items(services, session, [item])
    return InboxItemOut.model_validate(item)
