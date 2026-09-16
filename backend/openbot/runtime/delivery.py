from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.schemas import InboxItemOut, MessageOut, to_json
from openbot.db.models import Actor, InboxItem, Message, Run, Thread, ThreadParticipant, utcnow
from openbot.runtime import memory
from openbot.runtime.router import parse_mentions, resolve_targets
from openbot.tools.builtin.workspace import thread_workspace_root, validate_workspace_directory

log = logging.getLogger(__name__)

HOP_LIMIT_NOTICE = "Bot-to-bot hop limit reached; a human message resets it."
HUMAN_HANDLE = "you"
DEFAULT_BOT_HANDLE = "chief_of_staff"


@dataclass
class PostResult:
    message: Message
    addressed: list[Actor]
    unaddressed: bool
    items: list[InboxItem] = field(default_factory=list)


async def actor_by_handle(session: AsyncSession, handle: str) -> Actor | None:
    return (await session.execute(select(Actor).where(Actor.handle == handle))).scalar_one_or_none()


async def human_actor(session: AsyncSession) -> Actor:
    actor = await actor_by_handle(session, HUMAN_HANDLE)
    if actor is None:
        raise LookupError("human actor @you does not exist")
    return actor


async def _actors_by_handle(session: AsyncSession) -> dict[str, Actor]:
    return {a.handle: a for a in (await session.execute(select(Actor))).scalars().all()}


async def _participants(session: AsyncSession, thread_id: str) -> list[ThreadParticipant]:
    return list((await session.execute(select(ThreadParticipant).where(ThreadParticipant.thread_id == thread_id))).scalars().all())


async def notify(services, actor_ids: Iterable[str]) -> None:
    if services.actors is None:
        return
    for aid in dict.fromkeys(actor_ids):
        await services.actors.notify(aid)


async def _publish_items(services, items: list[InboxItem]) -> None:
    for it in items:
        await services.bus.publish("inbox.updated", it.thread_id, to_json(InboxItemOut, it))


async def create_thread(services, session: AsyncSession, *, title: str, handles: list[str], created_by: Actor | None,
                        external_ref: str | None = None, include_human: bool = True,
                        default_bot_handle: str | None = None, working_directory: str | None = None) -> Thread:
    by_handle = await _actors_by_handle(session)
    unknown = [h for h in handles if h not in by_handle]
    if unknown:
        raise ValueError(f"unknown handles: {unknown}")
    effective_default = default_bot_handle or DEFAULT_BOT_HANDLE
    default_bot = by_handle.get(effective_default)
    if default_bot is not None and default_bot.kind != "bot":
        raise ValueError(f"default bot must be a bot: {effective_default}")
    if default_bot_handle is not None and default_bot is None:
        raise ValueError(f"unknown default bot: {effective_default}")
    try:
        normalized_working_directory = validate_workspace_directory(services.settings.workspace_root, working_directory)
    except ValueError as e:
        msg = str(e)
        if "working_directory" not in msg:
            msg = f"invalid working_directory: {msg}"
        raise ValueError(msg) from e
    thread = Thread(title=title, created_by_actor_id=created_by.id if created_by else None,
                    default_bot_actor_id=default_bot.id if default_bot else None,
                    working_directory=normalized_working_directory, external_ref=external_ref)
    session.add(thread)
    await session.flush()
    log.info("thread %s created: title=%r handles=%s default_bot=%s working_directory=%s tool_root=%s",
             thread.id, title, handles, effective_default if default_bot else None, normalized_working_directory or ".",
             thread_workspace_root(services.settings.workspace_root, normalized_working_directory))
    ids = {by_handle[h].id for h in handles}
    if created_by:
        ids.add(created_by.id)
    if default_bot:
        ids.add(default_bot.id)
    if include_human and HUMAN_HANDLE in by_handle:
        ids.add(by_handle[HUMAN_HANDLE].id)
    for aid in ids:
        session.add(ThreadParticipant(thread_id=thread.id, actor_id=aid))
    await session.commit()
    return thread


async def post_message(services, session: AsyncSession, *, thread_id: str, sender: Actor | None, content: str,
                       to_handles: Iterable[str] = (), hop: int = 0, run_id: str | None = None,
                       meta: dict | None = None) -> PostResult:
    thread = await session.get(Thread, thread_id)
    if thread is None:
        raise LookupError("thread not found")
    by_handle = await _actors_by_handle(session)
    by_id = {a.id: a for a in by_handle.values()}
    to_handles = list(to_handles)
    unknown = [h for h in to_handles if h not in by_handle]
    if unknown:
        raise ValueError(f"unknown handles: {unknown}")
    mentioned = parse_mentions(content)
    parts = await _participants(session, thread_id)
    part_ids = [p.actor_id for p in parts]
    thread_bot_ids = [aid for aid in part_ids if aid in by_id and by_id[aid].kind == "bot"]
    default_bot_id = thread.default_bot_actor_id
    if default_bot_id is not None:
        default_bot = by_id.get(default_bot_id)
        if default_bot is None or default_bot.kind != "bot":
            default_bot_id = None
    if default_bot_id is None and DEFAULT_BOT_HANDLE in by_handle:
        default_bot_id = by_handle[DEFAULT_BOT_HANDLE].id
    targets = resolve_targets(sender=sender, mentioned_handles=mentioned, to_handles=to_handles,
                              actors_by_handle=by_handle, thread_bot_ids=thread_bot_ids,
                              default_bot_id=default_bot_id)
    unaddressed = sender is not None and not targets and not (mentioned or to_handles)
    now = utcnow()
    msg = Message(thread_id=thread_id, sender_actor_id=sender.id if sender else None,
                  sender_kind=sender.kind if sender else "system", sender_name=sender.name if sender else "system",
                  content=content, mentions=[by_handle[h].id for h in mentioned if h in by_handle],
                  hop=hop, run_id=run_id, meta=meta or {}, created_at=now)
    session.add(msg)
    thread.last_message_at = now
    thread.updated_at = now
    if sender is not None and hop == 0:
        thread.hop_limit_notified = False
    for bot in targets:
        if bot.id not in part_ids:
            session.add(ThreadParticipant(thread_id=thread_id, actor_id=bot.id))
            part_ids.append(bot.id)
    messages = [msg]
    if targets and hop >= services.settings.max_bot_hops:
        if not thread.hop_limit_notified:
            notice = Message(thread_id=thread_id, sender_kind="system", sender_name="system", content=HOP_LIMIT_NOTICE,
                             created_at=utcnow(), meta={"kind": "hop_limit"})
            session.add(notice)
            messages.append(notice)
            thread.hop_limit_notified = True
        targets = []
    await session.flush()
    items: list[InboxItem] = []
    for bot in targets:
        items.append(InboxItem(actor_id=bot.id, thread_id=thread_id, kind="message", message_id=msg.id))
    for m in messages:
        for aid in part_ids:
            a = by_id.get(aid)
            if a is None or a.kind == "bot" or (sender is not None and a.id == sender.id):
                continue
            items.append(InboxItem(actor_id=a.id, thread_id=thread_id, kind="message", message_id=m.id))
    session.add_all(items)
    await session.commit()
    for m in messages:
        if services.store is not None:
            await memory.index_message(services.store, m)
        await services.bus.publish("message.created", thread_id, to_json(MessageOut, m))
    await _publish_items(services, items)
    await notify(services, [it.actor_id for it in items])
    return PostResult(message=msg, addressed=targets, unaddressed=unaddressed, items=items)


async def deliver_question(services, run: Run, interrupt: dict) -> list[InboxItem]:
    async with services.session_factory() as session:
        parts = await _participants(session, run.thread_id)
        actors = {a.id: a for a in (await session.execute(select(Actor).where(Actor.id.in_([p.actor_id for p in parts])))).scalars()}
        items = [InboxItem(actor_id=a.id, thread_id=run.thread_id, kind="question", run_id=run.id,
                           payload={"run_id": run.id, "bot_id": run.actor_id, "interrupt": interrupt})
                 for a in actors.values() if a.kind in ("human", "external")]
        session.add_all(items)
        await session.commit()
    await _publish_items(services, items)
    await notify(services, [it.actor_id for it in items])
    return items


async def ack_items(services, session: AsyncSession, items: list[InboxItem]) -> None:
    for it in items:
        it.status, it.processed_at = "done", utcnow()
    await session.commit()
    await _publish_items(services, items)
