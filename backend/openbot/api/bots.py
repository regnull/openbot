from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.actors import handle_taken
from openbot.api.deps import get_services, get_session
from openbot.api.schemas import BotCreate, BotOut, BotUpdate, bot_out
from openbot.db.models import OPEN_RUN_STATUSES, Actor, BotProfile, Run, Thread
from openbot.services import Services

router = APIRouter(prefix="/bots", tags=["bots"])
ACTOR_FIELDS = ("handle", "name", "description", "enabled")


def _validate_tools(services: Services, tool_names: list[str], approval_tools: list[str]) -> None:
    if tool_names:
        unknown = ([t for t in tool_names if not services.registry.has(t)] if services.registry is not None
                   else list(tool_names))
        if unknown:
            raise HTTPException(422, f"unknown tools: {unknown}")
    extra = [t for t in approval_tools if t not in tool_names]
    if extra:
        raise HTTPException(422, f"approval_tools must be a subset of tool_names: {extra}")


async def _get_bot_or_404(session: AsyncSession, bot_id: str) -> Actor:
    actor = await session.get(Actor, bot_id)
    if not actor or actor.kind != "bot":
        raise HTTPException(404, "bot not found")
    return actor


@router.get("", response_model=list[BotOut])
async def list_bots(session: AsyncSession = Depends(get_session)):
    actors = (await session.execute(select(Actor).where(Actor.kind == "bot").order_by(Actor.created_at))).scalars().all()
    return [bot_out(a) for a in actors]


@router.post("", response_model=BotOut, status_code=201)
async def create_bot(body: BotCreate, session: AsyncSession = Depends(get_session),
                     services: Services = Depends(get_services)):
    _validate_tools(services, body.tool_names, body.approval_tools)
    if await handle_taken(session, body.handle):
        raise HTTPException(409, "handle already exists")
    data = body.model_dump()
    actor = Actor(kind="bot", **{k: data.pop(k) for k in ACTOR_FIELDS}, bot=BotProfile(**data))
    session.add(actor)
    await session.commit()
    return bot_out(actor)


@router.get("/{bot_id}", response_model=BotOut)
async def get_bot(bot_id: str, session: AsyncSession = Depends(get_session)):
    return bot_out(await _get_bot_or_404(session, bot_id))


@router.patch("/{bot_id}", response_model=BotOut)
async def update_bot(bot_id: str, body: BotUpdate, session: AsyncSession = Depends(get_session),
                     services: Services = Depends(get_services)):
    actor = await _get_bot_or_404(session, bot_id)
    data = body.model_dump(exclude_unset=True)
    _validate_tools(services, data.get("tool_names", actor.bot.tool_names), data.get("approval_tools", actor.bot.approval_tools))
    if "handle" in data and data["handle"] != actor.handle and await handle_taken(session, data["handle"]):
        raise HTTPException(409, "handle already exists")
    for k, v in data.items():
        setattr(actor if k in ACTOR_FIELDS else actor.bot, k, v)
    await session.commit()
    return bot_out(actor)


@router.delete("/{bot_id}", status_code=204)
async def delete_bot(bot_id: str, session: AsyncSession = Depends(get_session)):
    actor = await _get_bot_or_404(session, bot_id)
    if (await session.execute(select(Run.id).where(Run.actor_id == bot_id, Run.status.in_(OPEN_RUN_STATUSES)))).first():
        raise HTTPException(409, "bot has open runs")
    for thread in (await session.execute(select(Thread).where(Thread.default_bot_actor_id == bot_id))).scalars():
        thread.default_bot_actor_id = None
    await session.delete(actor)
    await session.commit()
