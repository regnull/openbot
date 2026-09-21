import pytest
from langchain.tools import ToolRuntime
from sqlalchemy import select

from openbot.db.models import Message
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.tools.builtin.core import (
    CORE_TOOLS,
    list_bots,
    read_history,
    recall_messages,
)
from openbot.tools.context import RunContext
from tests.factories import bot_actor


@pytest.fixture(autouse=True)
async def _no_actor_runs(services):
    """These tests exercise the CORE_TOOLS directly, using `eng`/`rev` and `setup()`'s posted messages
    only as fixture data; nothing here calls into a run. With the actor system running, `setup()`'s
    unmentioned human messages (each auto-routed to `eng`, the thread's only bot) wake eng's worker in
    the background, and it can race ahead of the test: enough `await`s happen inside `post_message`
    (session commits, activity.record) for the worker's task to interleave and even finish a full run
    between `setup()`'s three posts, before assertions that expect only those three messages to exist.
    Stopping the actor system removes the race without changing what any test asserts."""
    await services.actors.stop()


def rt(services, bot, thread_id, hop=1):
    ctx = RunContext(bot.id, bot.handle, bot.name, thread_id, "run", services.settings.workspace_root,
                     services, None, hop)
    return ToolRuntime(context=ctx, store=services.store, state={}, tool_call_id="c", config={}, stream_writer=lambda *_: None)


async def setup(services):
    async with services.session_factory() as s:
        eng, rev = bot_actor("eng", description="builds"), bot_actor("rev", description="reviews")
        s.add_all([eng, rev])
        await s.commit()
        you = await human_actor(s)
        services.settings.workspace_root.mkdir(parents=True, exist_ok=True)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you)
        for i in range(3):
            await post_message(services, s, thread_id=t.id, sender=you, content=f"note {i} about widgets")
        return eng, rev, t


def test_names():
    assert [t.name for t in CORE_TOOLS] == ["list_bots", "ask_human", "read_history", "recall_messages"]


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


