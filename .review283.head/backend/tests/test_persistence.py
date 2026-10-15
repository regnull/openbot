from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore
from langgraph.store.sqlite import AsyncSqliteStore

from openbot.config import Settings
from openbot.runtime.persistence import open_langgraph_backends, sqlite_path


def test_sqlite_path():
    assert sqlite_path("sqlite+aiosqlite:///./openbot.db") == "./openbot.db"
    assert sqlite_path("sqlite+aiosqlite:///:memory:") == ":memory:"


async def test_memory_backends():
    st = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    async with open_langgraph_backends(st, None) as (saver, store):
        assert isinstance(saver, InMemorySaver) and isinstance(store, InMemoryStore)


async def test_sqlite_backends(tmp_path):
    st = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/app.db")
    async with open_langgraph_backends(st, None) as (saver, store):
        assert isinstance(saver, AsyncSqliteSaver) and isinstance(store, AsyncSqliteStore)
        await store.aput(("bots", "b1", "memories"), "k", {"content": "likes tests"})
        item = await store.aget(("bots", "b1", "memories"), "k")
        assert item.value["content"] == "likes tests"
    assert (tmp_path / "app.langgraph.db").exists()
