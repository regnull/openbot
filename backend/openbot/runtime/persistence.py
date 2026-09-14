from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from openbot.config import Settings


def sqlite_path(url: str) -> str:
    return url.split("///", 1)[1]


def _index(settings: Settings, embeddings):
    if embeddings is None:
        return None
    return {"dims": settings.embedding_dims, "embed": embeddings, "fields": ["content"]}


@asynccontextmanager
async def open_langgraph_backends(
    settings: Settings, embeddings
) -> AsyncIterator[tuple[BaseCheckpointSaver, BaseStore]]:
    url = settings.database_url
    index = _index(settings, embeddings)
    if url.startswith("sqlite"):
        path = sqlite_path(url)
        if path == ":memory:":
            yield InMemorySaver(), InMemoryStore(index=index)
            return
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.store.sqlite import AsyncSqliteStore

        lg_path = Path(path).with_suffix(".langgraph.db")
        lg_path.parent.mkdir(parents=True, exist_ok=True)
        # The store issues its own explicit BEGIN/COMMIT around each batch, so its
        # connection must run in autocommit mode (isolation_level=None) -- otherwise
        # pysqlite3 auto-opens a transaction on the first DML in setup()'s migrations
        # and the store's later explicit BEGIN fails with "cannot start a transaction
        # within a transaction". The saver manages its own transactions differently
        # and works fine with aiosqlite's default isolation level.
        async with (
            aiosqlite.connect(lg_path) as c1,
            aiosqlite.connect(lg_path, isolation_level=None) as c2,
        ):
            for c in (c1, c2):
                await c.execute("PRAGMA journal_mode=WAL")
                await c.execute("PRAGMA busy_timeout=5000")
            saver = AsyncSqliteSaver(c1)
            await saver.setup()
            store = AsyncSqliteStore(c2, index=index)
            if hasattr(store, "setup"):
                await store.setup()
            yield saver, store
        return
    if url.startswith("postgresql"):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore

        dsn = "postgresql://" + url.split("://", 1)[1]
        async with (
            AsyncPostgresSaver.from_conn_string(dsn) as saver,
            AsyncPostgresStore.from_conn_string(dsn, index=index) as store,
        ):
            await saver.setup()
            await store.setup()
            yield saver, store
        return
    raise ValueError(f"unsupported DATABASE_URL: {url}")
