from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool
from sqlalchemy import or_, select

from openbot.api.schemas import bot_out
from openbot.db.models import Actor
from openbot.tools.context import RunContext


async def _target(session: Any, identifier: str) -> Actor | None:
    result = await session.execute(
        select(Actor).where(Actor.kind == "bot", or_(Actor.id == identifier, Actor.handle == identifier)).limit(1)
    )
    return result.scalar_one_or_none()


def _authorized(ctx: RunContext) -> bool:
    return ctx.actor_handle == "chief_of_staff"


@tool
async def read_bot_description(bot: str, runtime: ToolRuntime[RunContext]) -> str:
    """Read another bot's description and instructions. Available to the Chief of Staff."""
    ctx = runtime.context
    if not _authorized(ctx):
        return "error: only the Chief of Staff can inspect bot descriptions"
    async with ctx.services.session_factory() as session:
        actor = await _target(session, bot)
        if actor is None:
            return "error: bot not found"
        return f"@{actor.handle} ({actor.name})\ndescription: {actor.description}\ninstructions: {actor.bot.instructions}"


@tool
async def update_bot_description(
    bot: str,
    runtime: ToolRuntime[RunContext],
    description: str | None = None,
    instructions: str | None = None,
) -> str:
    """Update another bot's description and/or instructions. Available to the Chief of Staff."""
    ctx = runtime.context
    if not _authorized(ctx):
        return "error: only the Chief of Staff can update bot descriptions"
    if description is None and instructions is None:
        return "error: provide description or instructions"
    async with ctx.services.session_factory() as session:
        actor = await _target(session, bot)
        if actor is None:
            return "error: bot not found"
        if description is not None:
            actor.description = description
        if instructions is not None:
            actor.bot.instructions = instructions
        await session.commit()
        out = bot_out(actor)
        await ctx.services.bus.publish("bots.updated", None, out.model_dump(mode="json"))
        return f"updated @{actor.handle}"


BOT_PROFILE_TOOLS = [read_bot_description, update_bot_description]
