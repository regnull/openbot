from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.store.base import BaseStore
from langmem import (
    create_manage_memory_tool,
    create_memory_store_manager,
    create_search_memory_tool,
)

from openbot.db.models import Actor, Message

log = logging.getLogger(__name__)


def bot_namespace(bot_id: str) -> tuple[str, ...]:
    return ("bots", bot_id, "memories")


def thread_namespace(thread_id: str) -> tuple[str, ...]:
    return ("threads", thread_id, "messages")


def memory_tools(bot_id: str, store: BaseStore) -> list[BaseTool]:
    ns = bot_namespace(bot_id)
    return [
        create_manage_memory_tool(ns, store=store,
            instructions="Save durable facts, preferences, decisions and lessons you will need in "
                         "future conversations. Update or delete memories that became wrong."),
        create_search_memory_tool(ns, store=store),
    ]


async def relevant_memories(store: BaseStore, bot_id: str, query: str, limit: int = 8) -> list[str]:
    items = await store.asearch(bot_namespace(bot_id), query=query or None, limit=limit)
    out = []
    for it in items:
        v = it.value
        out.append(str(v.get("content", v)) if isinstance(v, dict) else str(v))
    return out


async def index_message(store: BaseStore, message: Message) -> None:
    await store.aput(thread_namespace(message.thread_id), message.id, {
        "content": message.content, "sender": message.sender_name,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "message_id": message.id,
    })


async def recall(store: BaseStore, thread_id: str, query: str, limit: int = 10) -> list[dict]:
    items = await store.asearch(thread_namespace(thread_id), query=query, limit=limit)
    return [dict(it.value) for it in items]


class MemoryReflector:
    """Debounced background extraction of long-term memories after runs."""

    def __init__(self, services, delay: float) -> None:
        self.services = services
        self.delay = delay
        self._pending: dict[str, tuple[Actor, list[BaseMessage]]] = {}
        self._timers: dict[str, asyncio.Task] = {}

    def make_manager(self, bot: Actor):
        model = self.services.model_factory(bot)
        return create_memory_store_manager(model, namespace=bot_namespace(bot.id),
                                           store=self.services.store,
                                           enable_inserts=True, enable_deletes=False)

    def schedule(self, bot: Actor, messages: list[BaseMessage]) -> None:
        _, existing = self._pending.get(bot.id, (bot, []))
        self._pending[bot.id] = (bot, [*existing, *messages])
        if t := self._timers.pop(bot.id, None):
            t.cancel()
        self._timers[bot.id] = asyncio.create_task(self._later(bot.id))

    async def _later(self, bot_id: str) -> None:
        await asyncio.sleep(self.delay)
        await self._reflect(bot_id)

    async def _reflect(self, bot_id: str) -> None:
        self._timers.pop(bot_id, None)
        item = self._pending.pop(bot_id, None)
        if not item:
            return
        bot, messages = item
        try:
            await self.make_manager(bot).ainvoke({"messages": messages})
        except Exception:
            log.exception("memory reflection failed for bot %s", bot.handle)

    async def flush(self) -> None:
        for bot_id in list(self._pending):
            if t := self._timers.pop(bot_id, None):
                t.cancel()
            await self._reflect(bot_id)

    async def shutdown(self) -> None:
        for t in self._timers.values():
            t.cancel()
        self._timers.clear()
        self._pending.clear()
