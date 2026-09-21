from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.schemas import InboxItemOut, MessageOut, to_json
from openbot.db.models import (
    Actor,
    InboxItem,
    Message,
    Run,
    Thread,
    ThreadParticipant,
    now_local,
    utcnow,
)
from openbot.runtime import activity, memory
from openbot.runtime.renaming import maybe_auto_rename
from openbot.runtime.router import parse_mentions, resolve_targets
from openbot.runtime.waiters import publish_waiters
from openbot.tools.builtin.workspace import thread_workspace_root, validate_workspace_directory

log = logging.getLogger(__name__)

HOP_LIMIT_NOTICE = "Bot-to-bot hop limit reached; a human message resets it."
HUMAN_HANDLE = "you"
DEFAULT_BOT_HANDLE = "chief_of_staff"
# Format for auto-generated thread titles when no title is provided:
# "YYYY-MM-DD HH:MM" in local time.
TITLE_TIME_FORMAT = "%Y-%m-%d %H:%M"


def generate_thread_title() -> str:
    """Generate a title for a new thread when the user gave none.

    Returns:
        Auto-generated title string (always timestamp-based).

    >>> generate_thread_title()  # doctest: +SKIP
    '2025-06-14 09:30'
    """
    return now_local().strftime(TITLE_TIME_FORMAT)


@dataclass
class PostResult:
    message: Message
    addressed: list[Actor]
    unaddressed: bool
    items: list[InboxItem] = field(default_factory=list)
    held: list[str] = field(default_factory=list)   # bot handles the sender mentioned but did not wake (see post_message)


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


async def notify(services, items: Iterable[InboxItem]) -> None:
    if services.actors is None:
        return
    for aid, thread_id in dict.fromkeys((it.actor_id, it.thread_id) for it in items):
        await services.actors.notify(aid, thread_id=thread_id)


async def _publish_items(services, items: list[InboxItem]) -> None:
    for it in items:
        await services.bus.publish("inbox.updated", it.thread_id, to_json(InboxItemOut, it))


def _system_notice(thread_id: str, content: str, *, created_at, mentions: list[str] | None = None, **meta) -> Message:
    """A wake-nobody message recording the platform's own bookkeeping (hop limit, a held hand-off).
    `sender_kind="system"` already means it never wakes anyone; `mentions` only decides whose *scoped*
    history includes it (see runner._prepare)."""
    return Message(thread_id=thread_id, sender_kind="system", sender_name="system", content=content,
                   mentions=mentions or [], created_at=created_at, meta=meta)


async def create_thread(services, session: AsyncSession, *, title: str, handles: list[str], created_by: Actor | None,
                        external_ref: str | None = None, include_human: bool = True,
                        default_bot_handle: str | None = None, working_directory: str | None = None,
                        kind: str = "chat") -> Thread:
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
    effective_title = title if title and title.strip() else None
    if effective_title is None:
        effective_title = generate_thread_title()

    thread = Thread(title=effective_title, kind=kind, created_by_actor_id=created_by.id if created_by else None,
                    default_bot_actor_id=default_bot.id if default_bot else None,
                    working_directory=normalized_working_directory, external_ref=external_ref)
    session.add(thread)
    await session.flush()
    log.info("thread %s created: title=%r handles=%s default_bot=%s working_directory=%s tool_root=%s",
             thread.id, effective_title, handles, effective_default if default_bot else None, normalized_working_directory or ".",
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
    await activity.record(services, "thread.created", thread_id=thread.id,
                          summary=f"thread {effective_title!r} created by @{created_by.handle if created_by else 'system'}",
                          kind=kind, handles=list(handles), default_bot=effective_default if default_bot else None,
                          working_directory=normalized_working_directory)
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
    # A bot hands off only when it has nothing else waiting in this thread: messages that arrived while
    # it was working are its next run's triggers, and if its reply woke another bot now, that bot would
    # act on a state the sender is about to revise (two review requests for one PR, each reviewed). The
    # reply is posted and the target added as a participant as usual; only the wake-up is held, and a
    # notice says so. A held hand-off is not left to the model to remember: BotActor._release_held_handoffs
    # (runtime/actors.py) delivers it, using this very message as the trigger, once the sender's queue for
    # this thread is empty -- unless a later reply from the sender already reached the target for real, in
    # which case this one is superseded and nothing more happens.
    held: list[str] = []
    pending_ids: list[str] = []
    if sender is not None and sender.kind == "bot" and targets:
        pending_ids = list((await session.execute(
            select(InboxItem.id).where(InboxItem.actor_id == sender.id, InboxItem.thread_id == thread_id,
                                       InboxItem.kind == "message", InboxItem.status == "queued"))).scalars().all())
        if pending_ids:
            held = [b.handle for b in targets]
    now = utcnow()
    msg = Message(thread_id=thread_id, sender_actor_id=sender.id if sender else None,
                  sender_kind=sender.kind if sender else "system", sender_name=sender.name if sender else "system",
                  content=content, mentions=[by_handle[h].id for h in mentioned if h in by_handle],
                  hop=hop, run_id=run_id, meta={**(meta or {}), **({"held_handoff": held} if held else {})}, created_at=now)
    session.add(msg)
    thread.last_message_at = now
    thread.updated_at = now
    if sender is not None and hop == 0:
        thread.hop_limit_notified = False
    # Even a held target is added as a participant now: the mention is real (recorded in
    # Message.mentions and shown in the message text), only the wake-up is deferred.
    for bot in targets:
        if bot.id not in part_ids:
            session.add(ThreadParticipant(thread_id=thread_id, actor_id=bot.id))
            part_ids.append(bot.id)
    messages = [msg]
    if held:
        n = len(pending_ids)
        notice = _system_notice(
            thread_id, created_at=now + timedelta(microseconds=1),
            content=f"@{sender.handle} has {n} newer message{'s' if n != 1 else ''} waiting in this thread; "
                    f"its hand-off to {', '.join('@' + h for h in held)} is held until it has handled them. "
                    f"{'It' if len(held) == 1 else 'They'} will be delivered automatically once @{sender.handle} "
                    f"is caught up here, whether or not @{sender.handle} mentions "
                    f"{'it' if len(held) == 1 else 'them'} again.",
            # Mentions the sender (so its own scoped history explains why it woke later) and the held
            # targets (so their scoped history includes this once they are woken).
            mentions=[sender.id, *(b.id for b in targets)],
            kind="handoff_held", bot=sender.handle, held=held, pending=n)
        session.add(notice)
        messages.append(notice)
        targets = []
    hop_limited = bool(targets) and hop >= services.settings.max_bot_hops
    if hop_limited:
        if not thread.hop_limit_notified:
            notice = _system_notice(thread_id, HOP_LIMIT_NOTICE, created_at=now + timedelta(microseconds=1), kind="hop_limit")
            session.add(notice)
            messages.append(notice)
            thread.hop_limit_notified = True
        dropped, targets = targets, []
    await session.flush()
    items: list[InboxItem] = []
    for bot in targets:
        items.append(InboxItem(actor_id=bot.id, thread_id=thread_id, kind="message", message_id=msg.id))
    # A direct thread is a one-shot exchange the operator reads in the bot's inbox view, so the reply is
    # not also pushed into the human's inbox as an unread message.
    for m in messages if thread.kind != "direct" else []:
        for aid in part_ids:
            a = by_id.get(aid)
            if a is None or a.kind == "bot" or (sender is not None and a.id == sender.id):
                continue
            items.append(InboxItem(actor_id=a.id, thread_id=thread_id, kind="message", message_id=m.id))
    session.add_all(items)
    await session.flush()       # the log rows below name the items by id
    sender_handle = sender.handle if sender else "system"
    addressed = [b.handle for b in targets]
    await activity.record(services, "message.posted", session=session, thread_id=thread_id, message_id=msg.id, run_id=run_id,
                          actor_id=sender.id if sender is not None and sender.kind == "bot" else None,
                          summary=f"@{sender_handle} posted (hop {hop}) -> {', '.join('@' + h for h in addressed) or 'nobody'}",
                          sender=sender_handle, sender_kind=msg.sender_kind, hop=hop, addressed=addressed, mentions=mentioned,
                          to=to_handles, unaddressed=unaddressed, content=activity.preview(content))
    if held:
        await activity.record(services, "message.handoff_held", session=session, thread_id=thread_id, message_id=msg.id,
                              actor_id=sender.id, run_id=run_id,
                              summary=f"@{sender.handle}'s hand-off to {', '.join('@' + h for h in held)} held: "
                                      f"{len(pending_ids)} newer message(s) queued for it in this thread",
                              held=held, pending_item_ids=pending_ids)
    if hop_limited:
        await activity.record(services, "message.hop_limit", session=session, level="warning", thread_id=thread_id,
                              message_id=msg.id, actor_id=sender.id if sender else None,
                              summary=f"hop {hop} >= max_bot_hops {services.settings.max_bot_hops}: not delivered to "
                                      f"{', '.join('@' + b.handle for b in dropped)}",
                              dropped=[b.handle for b in dropped], hop=hop, max_bot_hops=services.settings.max_bot_hops)
    for it in items:
        owner = by_id.get(it.actor_id)
        await activity.record(services, "inbox.enqueued", session=session, thread_id=thread_id, actor_id=it.actor_id,
                              item_id=it.id, message_id=it.message_id,
                              summary=f"queued {it.kind} for @{owner.handle if owner else it.actor_id}",
                              kind=it.kind, owner_kind=owner.kind if owner else None)
    await session.commit()
    for m in messages:
        if services.store is not None:
            await memory.index_message(services.store, m)
        await services.bus.publish("message.created", thread_id, to_json(MessageOut, m))
    await _publish_items(services, items)
    # Delivering to a bot that cannot pick the items up right now is what makes the thread window
    # show its waiting state, so publish it in the same breath as the inbox items themselves.
    await publish_waiters(services, session, thread_id)
    await notify(services, items)
    await maybe_auto_rename(services, thread_id)
    return PostResult(message=msg, addressed=targets, unaddressed=unaddressed, items=items, held=held)


async def deliver_question(services, run: Run, interrupt: dict) -> list[InboxItem]:
    async with services.session_factory() as session:
        parts = await _participants(session, run.thread_id)
        actors = {a.id: a for a in (await session.execute(select(Actor).where(Actor.id.in_([p.actor_id for p in parts])))).scalars()}
        items = [InboxItem(actor_id=a.id, thread_id=run.thread_id, kind="question", run_id=run.id,
                           payload={"run_id": run.id, "bot_id": run.actor_id, "interrupt": interrupt})
                 for a in actors.values() if a.kind in ("human", "external")]
        session.add_all(items)
        await session.flush()
        for it in items:
            await activity.record(services, "question.delivered", session=session, thread_id=run.thread_id, actor_id=run.actor_id,
                                  run_id=run.id, item_id=it.id,
                                  summary=f"{interrupt.get('kind', 'question')} delivered to @{actors[it.actor_id].handle}",
                                  recipient=actors[it.actor_id].handle, kind=interrupt.get("kind"),
                                  interrupt=activity.preview(interrupt))
        await session.commit()
    await _publish_items(services, items)
    await notify(services, items)
    return items


async def ack_items(services, session: AsyncSession, items: list[InboxItem]) -> None:
    threads = {it.thread_id for it in items}
    for it in items:
        it.status, it.processed_at = "done", utcnow()
        await activity.record(services, "inbox.acked", session=session, thread_id=it.thread_id, actor_id=it.actor_id,
                              item_id=it.id, run_id=it.run_id, message_id=it.message_id,
                              summary=f"{it.kind} item acked", kind=it.kind)
    await session.commit()
    await _publish_items(services, items)
    # Acking queued mail settles it without a run, so the waiting state it produced has to go too.
    for thread_id in threads:
        await publish_waiters(services, session, thread_id)
