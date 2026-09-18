from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool
from pydantic import ValidationError
from sqlalchemy import select

from openbot.api.schemas import BotCreate, bot_out
from openbot.db.models import Actor, BotProfile
from openbot.tools.context import RunContext


@tool
async def create_bot(
    handle: str,
    name: str,
    runtime: ToolRuntime[RunContext],
    description: str = "",
    icon: str | None = None,
    instructions: str = "",
    provider: str = "auto",
    model: str = "",
    model_settings: dict[str, Any] | None = None,
    tool_names: list[str] | None = None,
    approval_tools: list[str] | None = None,
    memory_enabled: bool = True,
    enabled: bool = True,
) -> str:
    """Create a bot definition that can immediately receive messages and participate in threads."""
    values: dict[str, Any] = {
        "handle": handle, "name": name, "description": description,
        "instructions": instructions, "provider": provider, "model": model,
        "model_settings": model_settings or {}, "tool_names": tool_names or [],
        "approval_tools": approval_tools or [], "memory_enabled": memory_enabled,
        "enabled": enabled,
    }
    if icon is not None:
        values["icon"] = icon
    try:
        body = BotCreate.model_validate(values)
    except ValidationError as exc:
        return f"error: invalid bot definition: {exc.errors()[0]['msg']}"

    services = runtime.context.services
    unknown = [n for n in body.tool_names if not services.registry.has(n)]
    if unknown:
        return f"error: unknown tools: {unknown}"
    extra = [n for n in body.approval_tools if n not in body.tool_names]
    if extra:
        return f"error: approval_tools must be a subset of tool_names: {extra}"

    async with services.session_factory() as session:
        taken = (await session.execute(select(Actor.id).where(Actor.handle == body.handle).limit(1))).first()
        if taken:
            return "error: handle already exists"
        data = body.model_dump()
        actor = Actor(kind="bot", **{k: data.pop(k) for k in ("handle", "name", "description", "enabled")},
                      bot=BotProfile(**data))
        session.add(actor)
        await session.commit()
        out = bot_out(actor)
        await services.bus.publish("bots.updated", None, out.model_dump(mode="json"))
        return f"created bot @{actor.handle} ({actor.id})"
