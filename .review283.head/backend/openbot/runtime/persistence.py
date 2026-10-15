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


async def reopen_memory_store(services) -> None:
    """Reopen the LangGraph store with the current embedding settings, so a change made in Settings (or
    the setup wizard) takes effect without a restart. The checkpointer is left untouched: it has no
    embedding-dependent state, and runs in flight were compiled against it (STO-2325: closing it made
    their next checkpoint write raise ValueError("no active connection")).

    The old store is not closed here either. Agents, memory tools and scheduled reflections capture the
    store at compile/schedule time, so a run may still be using it when the swap happens; closing the old
    stack would break it. It is parked on _owned_resources instead and closed with the rest of the
    process resources at shutdown. Tradeoff: each embedding change leaves one idle backend connection
    behind until shutdown (harmless for SQLite WAL; one pooled connection for Postgres).
    Vectors written with a different dimensionality are not migrated."""
    from contextlib import AsyncExitStack

    from openbot.runtime.providers import embeddings

    emb = embeddings(services.settings)
    if services.langgraph_stack is None:               # tests / in-memory installs
        services.store = InMemoryStore(index=_index(services.settings, emb))
        return
    new_stack = AsyncExitStack()
    try:
        _saver, store = await new_stack.enter_async_context(open_langgraph_backends(services.settings, emb))
    except BaseException:
        await new_stack.aclose()                       # don't leak the connections opened before the failure
        raise
    old = services.langgraph_stack
    services.store, services.langgraph_stack = store, new_stack
    services._owned_resources.append(old)              # closed by close_services, never under in-flight runs
