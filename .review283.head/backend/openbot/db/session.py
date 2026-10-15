from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from openbot.db.models import Base


def make_engine(url: str) -> AsyncEngine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()
    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _alembic_config(database_url: str) -> Config:
    here = Path(__file__).resolve().parent
    cfg = Config()
    cfg.set_main_option("script_location", str(here / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def ensure_sqlite_parent(database_url: str) -> None:
    if database_url.startswith("sqlite") and ":memory:" not in database_url:
        Path(database_url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)

async def run_migrations(database_url: str) -> None:
    await asyncio.to_thread(command.upgrade, _alembic_config(database_url), "head")


async def downgrade_migrations(database_url: str, revision: str) -> None:
    """Used by tests to prove downgrades work; nothing in the app calls this."""
    await asyncio.to_thread(command.downgrade, _alembic_config(database_url), revision)
