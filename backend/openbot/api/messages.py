from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.deps import get_services, get_session
from openbot.api.schemas import MessageCreate, MessageOut, PostMessageOut
from openbot.runtime.delivery import actor_by_handle, human_actor, post_message
from openbot.services import Services

router = APIRouter(tags=["messages"])


async def resolve_sender(session: AsyncSession, from_handle: str | None):
    if from_handle in (None, "", "you"):
        return await human_actor(session)
    sender = await actor_by_handle(session, from_handle)
    if sender is None:
        raise HTTPException(422, f"unknown sender handle: {from_handle}")
    return sender


@router.post("/threads/{thread_id}/messages", response_model=PostMessageOut, status_code=201)
async def post(thread_id: str, body: MessageCreate, session: AsyncSession = Depends(get_session),
               services: Services = Depends(get_services)):
    sender = await resolve_sender(session, body.from_handle)
    try:
        # Images ride in Message.meta, never through the bus payload (binary-safe).
        res = await post_message(services, session, thread_id=thread_id, sender=sender, content=body.content,
                                 to_handles=body.to, meta={"images": body.images} if body.images else None)
    except LookupError as e:
        raise HTTPException(404, "thread not found") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return PostMessageOut(message=MessageOut.model_validate(res.message), addressed=[a.handle for a in res.addressed],
                          unaddressed=res.unaddressed)
