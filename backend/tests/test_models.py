from datetime import timedelta

from sqlalchemy import inspect, select

from openbot.api.schemas import MessageOut, to_json
from openbot.db.models import Actor, InboxItem, Message, Run, Thread, ThreadParticipant
from openbot.db.session import create_all, make_engine, make_session_factory, run_migrations
from tests.factories import bot_actor, external_actor, human_actor


async def test_roundtrip():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sf = make_session_factory(engine)
    async with sf() as s:
        eng, you, ci = bot_actor("eng", instructions="build"), human_actor(), external_actor("ci", webhook_url="http://x")
        s.add_all([eng, you, ci])
        thread = Thread(title="t", working_directory="project")
        s.add(thread)
        await s.flush()
        s.add_all([ThreadParticipant(thread_id=thread.id, actor_id=eng.id),
                   ThreadParticipant(thread_id=thread.id, actor_id=you.id)])
        msg = Message(thread_id=thread.id, sender_actor_id=you.id, sender_kind="human", sender_name="You",
                      content="hi @eng", mentions=[eng.id])
        s.add(msg)
        await s.flush()
        s.add(InboxItem(actor_id=eng.id, thread_id=thread.id, kind="message", message_id=msg.id))
        s.add(Run(actor_id=eng.id, thread_id=thread.id))
        await s.commit()
    async with sf() as s:
        a = (await s.execute(select(Actor).where(Actor.handle == "eng"))).scalar_one()
        assert a.kind == "bot" and a.bot.instructions == "build" and a.bot.tool_names == [] and a.external is None
        c = (await s.execute(select(Actor).where(Actor.handle == "ci"))).scalar_one()
        assert c.external.webhook_url == "http://x" and c.bot is None
        item = (await s.execute(select(InboxItem))).scalar_one()
        assert item.status == "queued" and item.attempts == 0
        r = (await s.execute(select(Run))).scalar_one()
        assert r.status == "queued"
        thread = (await s.execute(select(Thread))).scalar_one()
        assert thread.working_directory == "project"
        m = (await s.execute(select(Message))).scalar_one()
        assert m.hop == 0 and m.mentions == [a.id]
        await s.delete(a)
        await s.commit()


async def test_timestamps_are_tz_aware_utc_on_reread(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/tz.db"
    engine = make_engine(url)
    await create_all(engine)
    sf = make_session_factory(engine)
    async with sf() as s:
        thread = Thread(title="t")
        s.add(thread)
        await s.flush()
        msg = Message(thread_id=thread.id, sender_kind="human", sender_name="You", content="hi")
        s.add(msg)
        await s.commit()
        thread_id, message_id = thread.id, msg.id

    # Re-read in a fresh session: SQLite loses tzinfo on round-trip unless the
    # UTCDateTime decorator re-attaches it.
    async with sf() as s:
        reread_thread = (await s.execute(select(Thread).where(Thread.id == thread_id))).scalar_one()
        reread_message = (await s.execute(select(Message).where(Message.id == message_id))).scalar_one()

        for obj in (reread_thread, reread_message):
            assert obj.created_at.tzinfo is not None
            assert obj.created_at.utcoffset() == timedelta(0)
        assert reread_thread.updated_at.tzinfo is not None
        assert reread_thread.updated_at.utcoffset() == timedelta(0)

        payload = to_json(MessageOut, reread_message)
        assert payload["created_at"].endswith("+00:00") or payload["created_at"].endswith("Z")


async def test_migrations_create_schema(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
        cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("threads")})
        bot_cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("bot_profiles")})
    assert {"actors", "bot_profiles", "external_profiles", "threads", "thread_participants", "messages",
            "inbox_items", "runs", "run_events"} <= set(names)
    assert "default_bot_actor_id" in cols
    assert "working_directory" in cols
    assert "icon" in bot_cols
