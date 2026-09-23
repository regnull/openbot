from __future__ import annotations

from datetime import timedelta

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from openbot.db.models import Actor, ScheduledMessage, Thread, ThreadParticipant, utcnow
from openbot.tools.context import RunContext


async def _validate_recipients(session, thread_id: str, handles: list[str]) -> str | None:
    if await session.get(Thread, thread_id) is None:
        return "target thread does not exist"
    actors = {a.handle: a for a in (await session.execute(select(Actor))).scalars()}
    unknown = [h for h in handles if h not in actors or actors[h].kind != "bot" or not actors[h].enabled]
    if unknown:
        return f"unknown or unavailable recipients: {unknown}"
    participants = set((await session.execute(
        select(ThreadParticipant.actor_id).where(ThreadParticipant.thread_id == thread_id)
    )).scalars())
    outside = [h for h in handles if actors[h].id not in participants]
    return f"recipients are not in the target thread: {outside}" if outside else None


@tool
async def schedule_message(delay_seconds: int, content: str, to: list[str] | None = None,
                           runtime: ToolRuntime[RunContext] = None) -> str:
    """Schedule one message in this thread. delay_seconds must be 1..31536000."""
    if delay_seconds < 1 or delay_seconds > 31_536_000:
        return "Error: delay_seconds must be between 1 and 31536000"
    if not content.strip() or len(content) > 20_000:
        return "Error: content must be 1..20000 characters"
    ctx = runtime.context
    recipients = list(dict.fromkeys(to or []))
    async with ctx.services.session_factory() as session:
        error = await _validate_recipients(session, ctx.thread_id, recipients)
        if error:
            return f"Error: {error}"
        job = ScheduledMessage(thread_id=ctx.thread_id, sender_actor_id=ctx.actor_id,
                               to_handles=recipients, content=content,
                               due_at=utcnow() + timedelta(seconds=delay_seconds))
        session.add(job)
        await session.commit()
        job_id, due_at = job.id, job.due_at
    await ctx.services.bus.publish("scheduled.updated", ctx.thread_id, {"id": job_id, "status": "pending"})
    return f"Scheduled message {job_id} for {due_at.isoformat()}"


@tool
async def list_scheduled_messages(runtime: ToolRuntime[RunContext]) -> str:
    """List this bot's scheduled messages and terminal outcomes."""
    async with runtime.context.services.session_factory() as session:
        rows = (await session.execute(select(ScheduledMessage).where(
            ScheduledMessage.sender_actor_id == runtime.context.actor_id
        ).order_by(ScheduledMessage.due_at.desc()).limit(50))).scalars()
        return "\n".join(f"{j.id} {j.status} {j.due_at.isoformat()} {j.content[:80]}" for j in rows) or "(none)"


SCHEDULING_TOOLS = [schedule_message, list_scheduled_messages]
