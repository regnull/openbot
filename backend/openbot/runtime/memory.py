from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.store.base import BaseStore, SearchItem
from langmem import (
    create_manage_memory_tool,
    create_memory_store_manager,
    create_search_memory_tool,
)

from openbot.db.models import Actor, Message

log = logging.getLogger(__name__)

# Memory is bot-scoped and shared across every thread the bot works in, so it may only hold what the
# bot learned about doing its job. Facts that are true inside one thread already reach the bot
# through the thread itself when the next run unrolls it.
MEMORY_SCOPE_RULE = (
    "Memory is your own long-term knowledge and is shared across every thread you work in. Store only "
    "durable, bot-level knowledge: how to do your job, team conventions and process (for example "
    "'always wait for CI before merging'), the human's standing preferences, and lessons learned. "
    "Never store facts that are only true inside one thread or task: task status, PR or issue numbers, "
    "file names, branch names, or decisions made for a single conversation. Those live in the thread."
)
REFLECTION_INSTRUCTIONS = (
    "Review the conversation and extract memories worth keeping for future conversations. "
    + MEMORY_SCOPE_RULE
    + " If the conversation contains nothing durable and bot-level, extract nothing."
)


def bot_namespace(bot_id: str) -> tuple[str, ...]:
    return ("bots", bot_id, "memories")


def thread_namespace(thread_id: str) -> tuple[str, ...]:
    return ("threads", thread_id, "messages")


def _memory_value(content: object) -> dict[str, object]:
    """Return the structured value expected by langmem's store manager."""
    return {"kind": "Memory", "content": {"content": str(content)}}


def _legacy_memory_content(value: dict) -> object:
    if "content" not in value:
        return dict(value)
    content = value["content"]
    if isinstance(content, dict) and set(content) == {"content"}:
        return content["content"]
    return content


def _normalize_memory_search_items(items: list[SearchItem]) -> list[SearchItem]:
    """Upgrade old manage_memory-tool values before MemoryStoreManager reads them.

    Older memories were written as {"content": "..."}, while langmem's
    reflection manager expects search results to have {"kind", "content"}.
    Any malformed/non-dict search result is also coerced into an unstructured
    Memory so one bad item cannot abort background reflection.
    Mutating SearchItem.value is sufficient for the manager invocation and
    preserves keys/timestamps/scores until the manager decides whether to
    write an update.
    """
    for item in items:
        value = item.value
        if not isinstance(value, dict):
            item.value = _memory_value(value)
            continue
        if "kind" in value and "content" in value:
            continue
        content = _legacy_memory_content(value)
        value.clear()
        value.update(_memory_value(content))
    return items


class ReflectionMemoryStore:
    """Store wrapper that normalizes legacy memory values for reflection searches."""

    def __init__(self, store: BaseStore) -> None:
        self._store = store

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    async def asearch(self, namespace_prefix: tuple[str, ...], /, **kwargs):
        items = await self._store.asearch(namespace_prefix, **kwargs)
        return _normalize_memory_search_items(items)


def memory_tools(bot_id: str, store: BaseStore) -> list[BaseTool]:
    ns = bot_namespace(bot_id)
    return [
        create_manage_memory_tool(ns, store=store, schema=str,
            instructions=MEMORY_SCOPE_RULE + " Update or delete memories that became wrong."),
        create_search_memory_tool(ns, store=store),
    ]


def memory_text(value: object) -> str:
    """The human-readable text of a stored memory, whatever shape wrote it (langmem manager, the
    manage_memory tool, or the legacy {"content": ...} form)."""
    if isinstance(value, dict):
        content = value.get("content", value)
        if isinstance(content, dict) and set(content) == {"content"}:
            content = content["content"]
        return str(content)
    return str(value)


async def relevant_memories(store: BaseStore, bot_id: str, query: str, limit: int = 8) -> list[str]:
    items = await store.asearch(bot_namespace(bot_id), query=query or None, limit=limit)
    return [memory_text(it.value) for it in items]


async def list_memories(store: BaseStore, bot_id: str, limit: int = 200) -> list[dict]:
    """Every memory of a bot, newest first, for the operator's Memory view."""
    items = await store.asearch(bot_namespace(bot_id), limit=limit)
    rows = [{"key": it.key, "content": memory_text(it.value), "created_at": it.created_at, "updated_at": it.updated_at}
            for it in items]
    rows.sort(key=lambda r: (r["updated_at"] or r["created_at"] or 0), reverse=True)
    return rows


async def delete_memory(store: BaseStore, bot_id: str, key: str) -> bool:
    ns = bot_namespace(bot_id)
    if await store.aget(ns, key) is None:
        return False
    await store.adelete(ns, key)
    return True


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
    """Debounced background extraction of long-term memories after runs.

    Batches are keyed by (bot, thread): a bot interleaves threads, and one extraction pass over two
    threads' transcripts cannot tell a durable pattern from a coincidence. Runs in the same thread
    that finish within `delay` of each other still reflect once.
    """

    def __init__(self, services, delay: float) -> None:
        self.services = services
        self.delay = delay
        self._pending: dict[tuple[str, str], tuple[Actor, list[BaseMessage]]] = {}
        self._timers: dict[tuple[str, str], asyncio.Task] = {}

    def make_manager(self, bot: Actor):
        model = self.services.model_factory(bot)
        return create_memory_store_manager(model, namespace=bot_namespace(bot.id),
                                           store=ReflectionMemoryStore(self.services.store),
                                           instructions=REFLECTION_INSTRUCTIONS,
                                           enable_inserts=True, enable_deletes=False)

    def schedule(self, bot: Actor, messages: list[BaseMessage], *, thread_id: str) -> None:
        key = (bot.id, thread_id)
        _, existing = self._pending.get(key, (bot, []))
        self._pending[key] = (bot, [*existing, *messages])
        if t := self._timers.pop(key, None):
            t.cancel()
        self._timers[key] = asyncio.create_task(self._later(key))

    async def _later(self, key: tuple[str, str]) -> None:
        await asyncio.sleep(self.delay)
        await self._reflect(key)

    async def _reflect(self, key: tuple[str, str]) -> None:
        self._timers.pop(key, None)
        item = self._pending.pop(key, None)
        if not item:
            return
        bot, messages = item
        try:
            # trustcall loops extract -> validate_or_retry -> extract whenever a model call yields no AI
            # message (a provider error, say) without counting an attempt, so an unhealthy upstream spun
            # until LangGraph's default limit of 25. Reflection is best-effort background work: cap it.
            await self.make_manager(bot).ainvoke({"messages": messages},
                                                 config={"recursion_limit": 12, "configurable": {"max_attempts": 2}})
        except Exception:
            log.exception("memory reflection failed for bot %s in thread %s", bot.handle, key[1])

    async def flush(self) -> None:
        for key in list(self._pending):
            if t := self._timers.pop(key, None):
                t.cancel()
            await self._reflect(key)

    async def shutdown(self) -> None:
        for t in self._timers.values():
            t.cancel()
        self._timers.clear()
        self._pending.clear()
