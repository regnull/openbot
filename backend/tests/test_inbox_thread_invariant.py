"""Every inbox item belongs to exactly one thread (docs/architecture.md, invariant 1)."""
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from openbot.db.models import InboxItem
from openbot.db.session import make_engine, run_migrations
from tests.factories import bot_actor


async def test_inbox_item_without_thread_is_rejected(services):
    async with services.session_factory() as s:
        eng = bot_actor("eng")
        s.add(eng)
        await s.flush()
        s.add(InboxItem(actor_id=eng.id, kind="message"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_migration_makes_inbox_thread_id_not_null(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {col["name"]: col for col in inspect(c).get_columns("inbox_items")})
    await engine.dispose()
    assert cols["thread_id"]["nullable"] is False


async def test_migration_adds_thread_kind_defaulting_to_chat(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {col["name"]: col for col in inspect(c).get_columns("threads")})
    await engine.dispose()
    assert cols["kind"]["nullable"] is False and "chat" in str(cols["kind"]["default"])
