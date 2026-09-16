from langchain.tools import ToolRuntime
from sqlalchemy import select

from openbot.db.models import Message, Thread
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.tools.builtin.core import (
    CORE_TOOLS,
    list_bots,
    read_history,
    recall_messages,
    start_thread,
)
from openbot.tools.context import RunContext
from tests.factories import bot_actor


def rt(services, bot, thread_id, hop=1, root=None, working_directory=None):
    ctx = RunContext(bot.id, bot.handle, bot.name, thread_id, "run", root or services.settings.workspace_root,
                     services, working_directory, hop)
    return ToolRuntime(context=ctx, store=services.store, state={}, tool_call_id="c", config={}, stream_writer=lambda *_: None)


async def setup(services):
    async with services.session_factory() as s:
        eng, rev = bot_actor("eng", description="builds"), bot_actor("rev", description="reviews")
        s.add_all([eng, rev])
        await s.commit()
        you = await human_actor(s)
        services.settings.workspace_root.mkdir(parents=True, exist_ok=True)
        (services.settings.workspace_root / "sub").mkdir(exist_ok=True)
        (services.settings.workspace_root / "current" / "child").mkdir(parents=True, exist_ok=True)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you)
        for i in range(3):
            await post_message(services, s, thread_id=t.id, sender=you, content=f"note {i} about widgets")
        return eng, rev, t


def test_names():
    assert [t.name for t in CORE_TOOLS] == ["list_bots", "start_thread", "ask_human", "read_history", "recall_messages"]
    assert "Do not use this to delegate" in start_thread.description


async def test_list_bots_and_history(services):
    eng, _rev, t = await setup(services)
    out = await list_bots.ainvoke({"runtime": rt(services, eng, t.id)})
    assert "@rev" in out and "reviews" in out and "@eng" not in out
    out = await read_history.ainvoke({"limit": 2, "runtime": rt(services, eng, t.id)})
    assert "note 1" in out and "note 2" in out and "note 0" not in out
    async with services.session_factory() as s:
        m1 = (await s.execute(select(Message).where(Message.content.like("note 1%")))).scalar_one()
    out = await read_history.ainvoke({"before_message_id": m1.id, "limit": 5, "runtime": rt(services, eng, t.id)})
    assert "note 0" in out and "note 1" not in out
    out = await recall_messages.ainvoke({"query": "widgets", "runtime": rt(services, eng, t.id)})
    assert "note" in out


async def test_start_thread(services):
    eng, _rev, t = await setup(services)
    out = await start_thread.ainvoke({"title": "side", "handles": ["rev"], "message": "@rev look at this",
                                      "working_directory": "sub", "runtime": rt(services, eng, t.id, hop=1)})
    assert out.startswith("started thread ")
    async with services.session_factory() as s:
        new = (await s.execute(select(Thread).where(Thread.title == "side"))).scalar_one()
        assert new.created_by_actor_id == eng.id
        assert new.working_directory == "sub"
        m = (await s.execute(select(Message).where(Message.thread_id == new.id))).scalar_one()
        assert m.sender_actor_id == eng.id and m.hop == 1
    out = await start_thread.ainvoke({"title": "nested", "handles": ["rev"], "message": "m",
                                      "working_directory": "child",
                                      "runtime": rt(services, eng, t.id, root=services.settings.workspace_root / "current",
                                                    working_directory="current")})
    assert out.startswith("started thread ")
    async with services.session_factory() as s:
        nested = (await s.execute(select(Thread).where(Thread.title == "nested"))).scalar_one()
        assert nested.working_directory == "current/child"
    assert "error" in await start_thread.ainvoke({"title": "x", "handles": ["ghost"], "message": "m", "runtime": rt(services, eng, t.id)})
    assert "error" in await start_thread.ainvoke({"title": "x", "handles": ["rev"], "message": "m",
                                                  "working_directory": "../bad", "runtime": rt(services, eng, t.id)})
