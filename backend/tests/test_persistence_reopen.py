"""STO-2325: reopening the memory store must not close the checkpointer under in-flight runs."""
import asyncio
from contextlib import AsyncExitStack

from langgraph.checkpoint.base import empty_checkpoint
from langgraph.store.memory import InMemoryStore

from openbot.config import Settings
from openbot.db.session import make_engine, make_session_factory
from openbot.main import close_services
from openbot.runtime.persistence import open_langgraph_backends, reopen_memory_store
from openbot.services import Services


class _SeqStore:
    """Minimal store that yields to the event loop before answering, so a reopen can land mid-operation."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def _delay(self):
        await asyncio.sleep(0)

    async def aget(self, namespace, key, *, refresh_ttl=None):
        await self._delay()
        return f"{self.name}:{key}"

    async def asearch(self, namespace_prefix, /, **kwargs):
        await self._delay()
        return [f"{self.name}:hit"]

    def __getattr__(self, name):
        raise AttributeError(f"unexpected store method: {name}")


def _services(store):
    """Services stub shaped like a test/in-memory install (langgraph_stack=None)."""
    from openbot.config import Settings
    return type("S", (), {"settings": Settings(_env_file=None), "langgraph_stack": None, "store": store,
                          "checkpointer": None, "_owned_resources": []})()


async def test_reopen_keeps_the_checkpointer():
    saver = object()
    services = _services(_SeqStore("old"))
    services.checkpointer = saver
    await reopen_memory_store(services)
    assert services.checkpointer is saver                       # untouched: in-flight runs keep their saver
    assert isinstance(services.store, InMemoryStore)            # reopened (no embeddings configured here)
    assert services.langgraph_stack is None


async def test_operation_started_before_reopen_still_works():
    services = _services(_SeqStore("old"))
    op = asyncio.create_task(services.store.aget(("bots", "b", "memories"), "k1"))
    await asyncio.sleep(0)                                      # let it suspend inside _delay
    await reopen_memory_store(services)                         # swap happens mid-operation
    assert await op == "old:k1"                                 # old store was not closed under it
    ns = ("bots", "b", "memories")
    await services.store.aput(ns, "k2", {"content": "after"})   # new store serves new compiles/tools
    assert (await services.store.aget(ns, "k2")).value["content"] == "after"


async def test_in_memory_reopen_leaves_nothing_parked():
    services = _services(_SeqStore("old"))
    await reopen_memory_store(services)
    assert services._owned_resources == []                      # no stack to park for an in-memory install


async def test_index_config_changes_with_the_new_store():
    from openbot.config import Settings
    services = _services(InMemoryStore())
    services.settings = Settings(_env_file=None, embedding_model="", embedding_dims=1536)
    await reopen_memory_store(services)
    assert getattr(services.store, "index_config", None) in (None, {})


async def test_sqlite_reopen_keeps_the_checkpointer_and_serves_holders(tmp_path):
    # The real failure mode: an SQLite-backed services object, a reopen while a run/reflection may hold
    # the old backends, then more work through the old objects. Used to raise
    # ValueError("no active connection") once reopen closed the old stack.
    st = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/app.db")
    engine = make_engine(st.database_url)
    services = Services(settings=st, session_factory=make_session_factory(engine), _owned_resources=[engine])
    try:
        stack = AsyncExitStack()
        services.checkpointer, services.store = await stack.enter_async_context(open_langgraph_backends(st, None))
        services.langgraph_stack = stack
        services._owned_resources.append(stack)
        old_store, old_checkpointer = services.store, services.checkpointer

        config = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
        await old_checkpointer.aput(config, empty_checkpoint(), {"source": "input", "step": -1, "writes": {}}, {})
        await old_store.aput(("bots", "b1", "memories"), "k1", {"content": "before"})

        await reopen_memory_store(services)

        # Work continues through the objects captured before the reopen; both raised
        # ValueError("no active connection") under the old reopen.
        await old_checkpointer.aput(config, empty_checkpoint(), {"source": "loop", "step": 0, "writes": {}}, {})
        await old_store.aput(("bots", "b1", "memories"), "k2", {"content": "after"})
        assert (await old_store.aget(("bots", "b1", "memories"), "k2")).value["content"] == "after"
        assert services.checkpointer is old_checkpointer            # untouched: in-flight runs keep it
        assert services.store is not old_store                      # new compiles see the reopened store
        # Both stacks share the database file, so earlier memories are visible through the new store too.
        assert (await services.store.aget(("bots", "b1", "memories"), "k1")).value["content"] == "before"
    finally:
        await close_services(services)                              # closes the current and the parked stack
