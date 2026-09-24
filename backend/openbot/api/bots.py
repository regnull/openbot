from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.actors import handle_taken
from openbot.api.deps import get_services, get_session
from openbot.api.schemas import (
    BotCreate,
    BotInboxItemOut,
    BotOut,
    BotUpdate,
    DirectPost,
    MemoryOut,
    MessageOut,
    PurgeOut,
    bot_out,
)
from openbot.api.tool_validation import known_tool
from openbot.db.models import (
    ACTIVE_RUN_STATUSES,
    OPEN_RUN_STATUSES,
    Actor,
    BotProfile,
    InboxItem,
    Message,
    Run,
    Thread,
)
from openbot.runtime import memory
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.services import Services

router = APIRouter(prefix="/bots", tags=["bots"])
ACTOR_FIELDS = ("handle", "name", "description", "enabled")


def _validate_tools(services: Services, tool_names: list[str], approval_tools: list[str]) -> None:
    if tool_names:
        unknown = [t for t in tool_names if not known_tool(services, t)]
        if unknown:
            raise HTTPException(422, f"unknown tools: {unknown}")
    extra = [t for t in approval_tools if t not in tool_names]
    if extra:
        raise HTTPException(422, f"approval_tools must be a subset of tool_names: {extra}")


def _validate_model(provider: str, model: str) -> None:
    if provider != "auto" and not model:
        raise HTTPException(422, 'model is required unless provider is "auto"')


async def _get_bot_or_404(session: AsyncSession, bot_id: str) -> Actor:
    actor = await session.get(Actor, bot_id)
    if not actor or actor.kind != "bot":
        raise HTTPException(404, "bot not found")
    return actor


@router.get("", response_model=list[BotOut])
async def list_bots(session: AsyncSession = Depends(get_session)):
    actors = (await session.execute(select(Actor).where(Actor.kind == "bot").order_by(Actor.created_at))).scalars().all()
    active_ids = set((await session.execute(select(Run.actor_id).where(Run.status.in_(ACTIVE_RUN_STATUSES)).distinct())).scalars().all())
    return [bot_out(a, active=a.id in active_ids) for a in actors]


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
    await services.bus.publish("bots.updated", None, bot_out(actor).model_dump(mode="json"))
    return bot_out(actor)


@router.get("/{bot_id}", response_model=BotOut)
async def get_bot(bot_id: str, session: AsyncSession = Depends(get_session)):
    actor = await _get_bot_or_404(session, bot_id)
    active = (await session.execute(select(Run.id).where(Run.actor_id == bot_id, Run.status.in_(ACTIVE_RUN_STATUSES)).limit(1))).first() is not None
    return bot_out(actor, active=active)


@router.patch("/{bot_id}", response_model=BotOut)
async def update_bot(bot_id: str, body: BotUpdate, session: AsyncSession = Depends(get_session),
                     services: Services = Depends(get_services)):
    actor = await _get_bot_or_404(session, bot_id)
    data = body.model_dump(exclude_unset=True)
    _validate_tools(services, data.get("tool_names", actor.bot.tool_names), data.get("approval_tools", actor.bot.approval_tools))
    _validate_model(data.get("provider", actor.bot.provider), data.get("model", actor.bot.model))
    if "handle" in data and data["handle"] != actor.handle and await handle_taken(session, data["handle"]):
        raise HTTPException(409, "handle already exists")
    for k, v in data.items():
        setattr(actor if k in ACTOR_FIELDS else actor.bot, k, v)
    await session.commit()
    active = (await session.execute(select(Run.id).where(Run.actor_id == bot_id, Run.status.in_(ACTIVE_RUN_STATUSES)).limit(1))).first() is not None
    out = bot_out(actor, active=active)
    await services.bus.publish("bots.updated", None, out.model_dump(mode="json"))
    return out


@router.delete("/{bot_id}", status_code=204)
async def delete_bot(bot_id: str, session: AsyncSession = Depends(get_session),
                     services: Services = Depends(get_services)):
    actor = await _get_bot_or_404(session, bot_id)
    if (await session.execute(select(Run.id).where(Run.actor_id == bot_id, Run.status.in_(OPEN_RUN_STATUSES)))).first():
        raise HTTPException(409, "bot has open runs")
    for thread in (await session.execute(select(Thread).where(Thread.default_bot_actor_id == bot_id))).scalars():
        thread.default_bot_actor_id = None
    await session.delete(actor)
    await session.commit()
    await services.bus.publish("bots.updated", None, {"id": bot_id, "deleted": True})


# --- inbox --------------------------------------------------------------------------------------------------

async def _bot_inbox_rows(session: AsyncSession, bot: Actor, items: list[InboxItem]) -> list[BotInboxItemOut]:
    msg_ids = [i.message_id for i in items if i.message_id]
    run_ids = [i.run_id for i in items if i.run_id]
    thread_ids = list({i.thread_id for i in items})
    msgs = {m.id: m for m in (await session.execute(select(Message).where(Message.id.in_(msg_ids)))).scalars()} if msg_ids else {}
    runs = {r.id: r for r in (await session.execute(select(Run).where(Run.id.in_(run_ids)))).scalars()} if run_ids else {}
    replies: dict[str, Message] = {}
    if run_ids:
        q = select(Message).where(Message.run_id.in_(run_ids), Message.sender_actor_id == bot.id).order_by(Message.created_at)
        for m in (await session.execute(q)).scalars():
            replies[m.run_id] = m           # the last message a run posted is its reply
    kinds = {t.id: t.kind for t in (await session.execute(select(Thread).where(Thread.id.in_(thread_ids)))).scalars()} if thread_ids else {}
    out = []
    for it in items:
        o = BotInboxItemOut.model_validate(it)
        o.message = MessageOut.model_validate(msgs[it.message_id]) if it.message_id in msgs else None
        o.thread_kind = kinds.get(it.thread_id, "chat")
        run = runs.get(it.run_id) if it.run_id else None
        o.run_status = run.status if run else None
        o.reply = MessageOut.model_validate(replies[it.run_id]) if it.run_id in replies else None
        out.append(o)
    return out


@router.get("/{bot_id}/inbox", response_model=list[BotInboxItemOut])
async def bot_inbox(bot_id: str, limit: int = Query(100, ge=1, le=200), session: AsyncSession = Depends(get_session)):
    """The bot's mailbox as the operator sees it: every item, newest first, with the run's status and reply."""
    bot = await _get_bot_or_404(session, bot_id)
    items = (await session.execute(select(InboxItem).where(InboxItem.actor_id == bot.id)
                                   .order_by(InboxItem.created_at.desc()).limit(limit))).scalars().all()
    return await _bot_inbox_rows(session, bot, list(items))


@router.post("/{bot_id}/inbox", response_model=BotInboxItemOut, status_code=201)
async def post_to_bot_inbox(bot_id: str, body: DirectPost, session: AsyncSession = Depends(get_session),
                            services: Services = Depends(get_services)):
    """Post straight into a bot's inbox. Each post gets its own hidden one-message thread, so the bot sees only
    this message plus its memories: an inbox is a queue of independent messages, not a conversation."""
    bot = await _get_bot_or_404(session, bot_id)
    you = await human_actor(session)
    content = body.content.strip()
    title = content.splitlines()[0][:60]
    thread = await create_thread(services, session, title=title, handles=[bot.handle], created_by=you, kind="direct")
    res = await post_message(services, session, thread_id=thread.id, sender=you, content=content, to_handles=[bot.handle])
    item = next(i for i in res.items if i.actor_id == bot.id)
    return (await _bot_inbox_rows(session, bot, [item]))[0]


@router.post("/{bot_id}/purge", response_model=PurgeOut)
async def purge_bot(bot_id: str, session: AsyncSession = Depends(get_session), services: Services = Depends(get_services)):
    """Cancel whatever the bot is doing (a live run, or one waiting on a question) and drop everything queued
    for it. The operator's way out when a bot is wedged: nothing is deleted, items and runs are marked cancelled."""
    await _get_bot_or_404(session, bot_id)
    return PurgeOut(**await services.actors.purge(bot_id))


# --- memory -------------------------------------------------------------------------------------------------

@router.get("/{bot_id}/memories", response_model=list[MemoryOut])
async def bot_memories(bot_id: str, session: AsyncSession = Depends(get_session), services: Services = Depends(get_services)):
    await _get_bot_or_404(session, bot_id)
    if services.store is None:
        return []
    return [MemoryOut(**row) for row in await memory.list_memories(services.store, bot_id)]


@router.delete("/{bot_id}/memories/{key}", status_code=204)
async def delete_bot_memory(bot_id: str, key: str, session: AsyncSession = Depends(get_session),
                            services: Services = Depends(get_services)):
    await _get_bot_or_404(session, bot_id)
    if services.store is None or not await memory.delete_memory(services.store, bot_id, key):
        raise HTTPException(404, "memory not found")
    return Response(status_code=204)
