from __future__ import annotations

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt
from sqlalchemy import select

from openbot.db.models import Actor, Message
from openbot.runtime import memory
from openbot.tools.builtin.workspace import thread_workspace_root, validate_workspace_directory
from openbot.tools.context import RunContext


@tool
async def list_bots(runtime: ToolRuntime[RunContext]) -> str:
    """List the other bots on this platform with their handles and what they do."""
    async with runtime.context.services.session_factory() as s:
        q = select(Actor).where(Actor.kind == "bot", Actor.enabled.is_(True)).order_by(Actor.handle)
        bots = (await s.execute(q)).scalars().all()
    return "\n".join(f"@{b.handle} ({b.name}): {b.description}" for b in bots
                     if b.id != runtime.context.actor_id) or "(none)"


@tool
async def start_thread(title: str, handles: list[str], message: str, runtime: ToolRuntime[RunContext],
                       working_directory: str | None = None) -> str:
    """Start a new thread with the given actor handles (bots, or "you" for the human) and post the first message.
    `working_directory`, when provided, must be an existing directory relative to this thread's current tool root.
    Mention bots with @handle in the message to wake them up."""
    from openbot.runtime.delivery import create_thread, post_message
    ctx = runtime.context
    async with ctx.services.session_factory() as s:
        me = await s.get(Actor, ctx.actor_id)
        try:
            next_working_directory = ctx.working_directory
            if working_directory is not None:
                current_relative = validate_workspace_directory(ctx.workspace_root, working_directory)
                selected_root = thread_workspace_root(ctx.workspace_root, current_relative)
                try:
                    relative_to_workspace = selected_root.relative_to(ctx.services.settings.workspace_root.resolve())
                except ValueError as e:
                    raise ValueError(f"working_directory escapes workspace root: {working_directory}") from e
                next_working_directory = relative_to_workspace.as_posix() if relative_to_workspace.parts else None
            t = await create_thread(ctx.services, s, title=title, handles=handles, created_by=me, include_human=False,
                                    working_directory=next_working_directory)
            await post_message(ctx.services, s, thread_id=t.id, sender=me, content=message, hop=ctx.hop)
        except ValueError as e:
            return f"error: {e}"
    return f"started thread {t.id}"


@tool
def ask_human(question: str) -> str:
    """Ask the human a question or request a decision. Your run pauses until they answer."""
    answer = interrupt({"kind": "question", "question": question})
    return f"Human answered: {answer}"


def _fmt(m: Message) -> str:
    return f"[{m.id}] {m.created_at.isoformat(timespec='seconds')} [{m.sender_name}]: {m.content}"


@tool
async def read_history(runtime: ToolRuntime[RunContext], before_message_id: str | None = None, limit: int = 20) -> str:
    """Read older messages of the current thread chronologically. Pass before_message_id to page further back."""
    ctx = runtime.context
    async with ctx.services.session_factory() as s:
        q = select(Message).where(Message.thread_id == ctx.thread_id)
        if before_message_id and (anchor := await s.get(Message, before_message_id)):
            q = q.where(Message.created_at < anchor.created_at)
        rows = (await s.execute(q.order_by(Message.created_at.desc()).limit(limit))).scalars().all()
    return "\n".join(_fmt(m) for m in reversed(rows)) or "(no messages)"


@tool
async def recall_messages(query: str, runtime: ToolRuntime[RunContext], limit: int = 10) -> str:
    """Semantic search over ALL messages in the current thread, including ones no longer in your context."""
    hits = await memory.recall(runtime.context.services.store, runtime.context.thread_id, query, limit)
    return "\n".join(f"[{h.get('message_id')}] {h.get('created_at')} [{h.get('sender')}]: {h.get('content')}" for h in hits) or "(no matches)"


CORE_TOOLS = [list_bots, start_thread, ask_human, read_history, recall_messages]
