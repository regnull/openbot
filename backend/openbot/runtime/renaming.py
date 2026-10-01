from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import HumanMessage
from sqlalchemy import select, update

from openbot.db.models import Actor, Message, Thread

log = logging.getLogger(__name__)
RENAME_AFTER_MESSAGES = 3


async def maybe_auto_rename(services, thread_id: str) -> None:
    """Ask the default bot's model for a useful title once, after the initial conversation. The rename is
    claimed here; the model call runs in the background, so the post that triggered it does not wait
    for a provider that may take seconds, or its whole timeout, to answer."""
    async with services.session_factory() as session:
        thread = await session.get(Thread, thread_id)
        if thread is None or thread.auto_renamed:
            return
        messages = list((await session.execute(
            select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at, Message.id)
        )).scalars())
        if len(messages) < RENAME_AFTER_MESSAGES:
            return
        actor = await session.get(Actor, thread.default_bot_actor_id) if thread.default_bot_actor_id else None
        if actor is None or actor.bot is None:
            return
        # Claim atomically so concurrent deliveries cannot both invoke the provider.
        result = await session.execute(
            update(Thread)
            .where(Thread.id == thread_id, Thread.auto_renamed.is_(False))
            .values(auto_renamed=True)
        )
        if result.rowcount != 1:
            return
        await session.commit()
        transcript = "\n".join(f"{m.sender_name}: {m.content}" for m in messages[:8])
    task = asyncio.create_task(_rename(services, thread_id, actor, transcript), name=f"thread-rename:{thread_id}")
    services._rename_tasks.add(task)
    task.add_done_callback(services._rename_tasks.discard)


async def _rename(services, thread_id: str, actor: Actor, transcript: str) -> None:
    prompt = HumanMessage(content=(
        "Suggest a concise, accurate title for this conversation. Return only the title, no quotes, "
        "markdown, or explanation. Use at most 80 characters.\n\n" + transcript
    ))
    try:
        response = await services.model_factory(actor).ainvoke([prompt])
        title = getattr(response, "content", "")
        if isinstance(title, list):
            title = "".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in title)
        title = str(title).strip().strip('"')[:80]
        if not title:
            return
        async with services.session_factory() as update_session:
            current = await update_session.get(Thread, thread_id)
            if current:
                current.title = title
                await update_session.commit()
        await services.bus.publish("thread.updated", thread_id, {"id": thread_id, "title": title})
    except Exception:
        log.exception("automatic thread rename failed for %s", thread_id)


async def finish_renames(services, timeout: float | None = None) -> None:
    """Wait for the titles still being generated. Past `timeout` they are cancelled; the claim stays
    consumed, like after a failed call."""
    tasks = list(services._rename_tasks)
    if not tasks:
        return
    _, pending = await asyncio.wait(tasks, timeout=timeout)
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
