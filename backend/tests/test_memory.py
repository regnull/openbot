import asyncio
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage
from langgraph.store.memory import InMemoryStore

from openbot.db.models import Actor, Message
from openbot.runtime.memory import (
    MemoryReflector,
    ReflectionMemoryStore,
    bot_namespace,
    index_message,
    memory_tools,
    recall,
    relevant_memories,
)
from tests.fakes import ScriptedChatModel


async def test_memory_tools_roundtrip():
    store = InMemoryStore()
    manage, search = memory_tools("b1", store)
    assert manage.name == "manage_memory" and search.name == "search_memory"
    await manage.ainvoke({"content": "User prefers squash merges", "action": "create"})
    mems = await relevant_memories(store, "b1", "merge", limit=5)
    assert mems == ["User prefers squash merges"]
    assert await relevant_memories(store, "other", "merge") == []


async def test_reflection_store_normalizes_legacy_memory_values():
    store = InMemoryStore()
    namespace = bot_namespace("b1")
    await store.aput(namespace, "legacy", {"content": "User prefers squash merges"})

    wrapped = ReflectionMemoryStore(store)
    items = await wrapped.asearch(namespace, query="merge", limit=5)

    assert items[0].key == "legacy"
    assert items[0].value == {
        "kind": "Memory",
        "content": {"content": "User prefers squash merges"},
    }


async def test_reflection_store_normalizes_malformed_memory_values():
    store = InMemoryStore()
    namespace = bot_namespace("b1")
    await store.aput(namespace, "missing_content", {"source": "old-tool"})

    items = await ReflectionMemoryStore(store).asearch(namespace, query="old-tool", limit=5)

    assert items[0].value == {
        "kind": "Memory",
        "content": {"content": "{'source': 'old-tool'}"},
    }


async def test_reflection_store_leaves_structured_memory_values_unchanged():
    store = InMemoryStore()
    namespace = bot_namespace("b1")
    structured = {"kind": "Memory", "content": {"content": "Already structured"}}
    await store.aput(namespace, "structured", structured)

    items = await ReflectionMemoryStore(store).asearch(namespace, query="structured", limit=5)

    assert items[0].value == structured


async def test_index_and_recall():
    store = InMemoryStore()
    m = Message(id="m1", thread_id="t1", sender_kind="human", sender_name="alice",
                content="the deploy key lives in vault", created_at=datetime.now(UTC))
    await index_message(store, m)
    hits = await recall(store, "t1", "deploy key", limit=5)
    assert hits[0]["message_id"] == "m1" and hits[0]["sender"] == "alice"
    assert await recall(store, "t2", "deploy key") == []


async def test_reflector_manager_tolerates_legacy_memory_values():
    class StubMemoryManager:
        async def ainvoke(self, inp, config=None):
            return []

    class Svc:
        def __init__(self):
            self.store = InMemoryStore()
            self.model_factory = lambda bot: ScriptedChatModel(messages=iter([]))

    services = Svc()
    bot = Actor(id="b1", kind="bot", handle="b", name="B")
    await services.store.aput(bot_namespace(bot.id), "legacy", {"content": "legacy memory"})

    manager = MemoryReflector(services, delay=10).make_manager(bot)
    manager.memory_manager = StubMemoryManager()

    assert await manager.ainvoke({"messages": [HumanMessage("remember this")]}) == []


async def test_reflector_debounces_and_flushes():
    calls = []

    class StubManager:
        async def ainvoke(self, inp, config=None):
            calls.append(inp)
            return []

    class Svc:
        store = InMemoryStore()
        model_factory = None

    r = MemoryReflector(Svc(), delay=10)
    r.make_manager = lambda bot: StubManager()
    bot = Actor(id="b1", kind="bot", handle="b", name="B")
    r.schedule(bot, [HumanMessage("one")])
    r.schedule(bot, [HumanMessage("two")])
    await asyncio.sleep(0.01)
    assert calls == []
    await r.flush()
    assert len(calls) == 1 and [m.content for m in calls[0]["messages"]] == ["one", "two"]
