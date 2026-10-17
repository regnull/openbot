"""The todo_write tool: a bot's todo list for one thread, saved in the database (issue #245)."""

import pytest
import pytest_asyncio
from langchain.tools import ToolRuntime
from pydantic import ValidationError
from sqlalchemy import inspect, select

from openbot.db.models import Actor, Run, Thread, ThreadTodoList
from openbot.db.session import make_engine, run_migrations
from openbot.runtime.delivery import create_thread, human_actor
from openbot.runtime.prompt import build_system_prompt_parts
from openbot.tools.builtin.todo import MAX_TODOS, TodoItem, load_todos, todo_write
from openbot.tools.context import RunContext
from tests.factories import bot_actor
from tests.fakes import ScriptedChatModel, ai, call
from tests.test_runner import get, make
from tests.test_token_efficiency import SummarizingScriptedModel

PLAN = [
    {"content": "Read the failing test", "status": "completed"},
    {"content": "Fix the parser", "status": "in_progress"},
    {"content": "Run the suite", "status": "pending"},
]


@pytest_asyncio.fixture
async def _no_actor_runs(services):
    """Nothing here needs a run; stop the actor system so no background run races the assertions."""
    await services.actors.stop()


def rt(services, bot, thread_id):
    ctx = RunContext(bot.id, bot.handle, bot.name, thread_id, "run", services.settings.workspace_root, services)
    return ToolRuntime(context=ctx, store=services.store, state={}, tool_call_id="c", config={},
                       stream_writer=lambda *_: None)


async def setup(services):
    async with services.session_factory() as s:
        eng, rev = bot_actor("eng"), bot_actor("rev")
        s.add_all([eng, rev])
        await s.commit()
        you = await human_actor(s)
        t1 = await create_thread(services, s, title="t1", handles=["eng", "rev"], created_by=you)
        t2 = await create_thread(services, s, title="t2", handles=["eng"], created_by=you)
        return eng, rev, t1, t2


async def saved(services, thread_id, actor_id):
    async with services.session_factory() as s:
        return await load_todos(s, thread_id, actor_id)


async def test_todo_write_saves_replaces_and_clears_the_list(services, _no_actor_runs):
    eng, _rev, t1, _t2 = await setup(services)

    out = await todo_write.ainvoke({"todos": PLAN, "runtime": rt(services, eng, t1.id)})
    assert out.startswith("Todo list updated (1/3 completed):")
    assert "[x] Read the failing test\n[>] Fix the parser\n[ ] Run the suite" in out
    assert await saved(services, t1.id, eng.id) == PLAN

    done = [{**i, "status": "completed"} for i in PLAN]
    await todo_write.ainvoke({"todos": done, "runtime": rt(services, eng, t1.id)})
    assert await saved(services, t1.id, eng.id) == done
    async with services.session_factory() as s:
        assert len((await s.execute(select(ThreadTodoList))).scalars().all()) == 1, "replaced, not appended"

    out = await todo_write.ainvoke({"todos": [], "runtime": rt(services, eng, t1.id)})
    assert out == "Todo list cleared."
    assert await saved(services, t1.id, eng.id) == []
    async with services.session_factory() as s:
        assert (await s.execute(select(ThreadTodoList))).scalars().all() == []


async def test_lists_are_kept_per_thread_and_per_bot(services, _no_actor_runs):
    eng, rev, t1, t2 = await setup(services)
    await todo_write.ainvoke({"todos": PLAN, "runtime": rt(services, eng, t1.id)})
    await todo_write.ainvoke({"todos": PLAN[:1], "runtime": rt(services, rev, t1.id)})

    assert await saved(services, t1.id, eng.id) == PLAN
    assert await saved(services, t1.id, rev.id) == PLAN[:1]
    assert await saved(services, t2.id, eng.id) == []


async def test_todo_write_publishes_the_full_list_on_the_thread(services, monkeypatch, _no_actor_runs):
    eng, _rev, t1, _t2 = await setup(services)
    published = []

    async def publish(event, thread_id, data):
        published.append((event, thread_id, data))

    monkeypatch.setattr(services.bus, "publish", publish)
    await todo_write.ainvoke({"todos": PLAN, "runtime": rt(services, eng, t1.id)})
    await todo_write.ainvoke({"todos": [], "runtime": rt(services, eng, t1.id)})

    assert published == [
        ("todos.updated", t1.id, {"actor_id": eng.id, "handle": "eng", "todos": PLAN}),
        ("todos.updated", t1.id, {"actor_id": eng.id, "handle": "eng", "todos": []}),
    ]


async def test_todo_write_trims_items_and_rejects_bad_ones(services, _no_actor_runs):
    eng, _rev, t1, _t2 = await setup(services)
    await todo_write.ainvoke({"todos": [{"content": "  Fix it  ", "status": "pending"}],
                              "runtime": rt(services, eng, t1.id)})
    assert await saved(services, t1.id, eng.id) == [{"content": "Fix it", "status": "pending"}]

    for bad in ({"content": "   ", "status": "pending"}, {"content": "x" * 501, "status": "pending"},
                {"content": "Fix it", "status": "done"}):
        with pytest.raises(ValidationError):
            TodoItem(**bad)

    too_many = [{"content": f"step {i}", "status": "pending"} for i in range(MAX_TODOS + 1)]
    out = await todo_write.ainvoke({"todos": too_many, "runtime": rt(services, eng, t1.id)})
    assert out.startswith("error:")
    assert await saved(services, t1.id, eng.id) == [{"content": "Fix it", "status": "pending"}]


def test_the_list_goes_in_the_dynamic_prompt_only():
    bot = bot_actor("eng")
    bot.id = "e"
    kw = {"bot": bot, "all_bots": [bot], "participants": ["You"], "memories": [], "workspace_root": "/w",
          "older_count": 0, "tool_names": ["todo_write"]}
    stable, dynamic = build_system_prompt_parts(**kw, todos=PLAN)
    assert "# Your todo list" in dynamic and "[>] Fix the parser" in dynamic
    assert "# Your todo list" not in stable
    assert "# Your todo list" not in build_system_prompt_parts(**kw)[1]


async def test_the_next_run_sees_the_saved_list(settings):
    """The list outlives the run that wrote it: the next run's system prompt carries it."""
    script = [ai(tool_calls=[call("todo_write", todos=PLAN)]), ai("on it")]
    services, eng, t, run = await make(settings, {"eng": script}, tool_names=["todo_write"])
    await services.runner.execute(run.id)
    assert (await get(services, Run, run.id)).status == "completed"

    async with services.session_factory() as s:
        bot, thread, again = await s.get(Actor, eng.id), await s.get(Thread, t.id), await s.get(Run, run.id)
    prompt, _inputs, _hop = await services.runner._prepare(bot, thread, again)
    dynamic = prompt.content[1]["text"]
    assert "# Your todo list" in dynamic and "[x] Read the failing test" in dynamic


async def test_a_bot_without_the_tool_gets_no_list_in_its_prompt(settings):
    services, eng, t, run = await make(settings, {"eng": []}, tool_names=["run_shell"])
    async with services.session_factory() as s:
        s.add(ThreadTodoList(thread_id=t.id, actor_id=eng.id, items=PLAN))
        await s.commit()
        bot, thread, again = await s.get(Actor, eng.id), await s.get(Thread, t.id), await s.get(Run, run.id)
    prompt, _inputs, _hop = await services.runner._prepare(bot, thread, again)
    assert "# Your todo list" not in prompt.content[1]["text"]


async def test_a_summarized_run_keeps_its_todo_list(settings):
    """Summarization can fold the todo_write calls away; the summary carries the saved list instead."""
    settings.summary_trigger_tokens = 300
    settings.summary_keep_messages = 4
    settings.context_trigger_tokens = 10_000  # keep clearing out of this test
    ScriptedChatModel.seen.clear()
    script = (
        [ai(tool_calls=[call("todo_write", cid="todo", todos=PLAN)])]
        + [ai(tool_calls=[call("run_shell", cid=f"c{i}", command=f"python3 -c \"print('step{i} ' + 'y'*400)\"")])
           for i in range(6)]
        + [ai("done")]
    )
    services, _eng, _t, run = await make(settings, {"eng": []}, tool_names=["run_shell", "todo_write"])
    services.model_factory = lambda actor: SummarizingScriptedModel(messages=iter(script))
    await services.runner.execute(run.id)
    assert (await get(services, Run, run.id)).status == "completed"

    final_prompt = ScriptedChatModel.seen[-1]
    summary = next(m for m in final_prompt if "SUMMARY: ran steps" in str(m.content))
    assert "# Your todo list" in summary.content and "[>] Fix the parser" in summary.content
    assert not any(m.type == "tool" and m.name == "todo_write" for m in final_prompt), \
        "the todo_write call itself was summarized away"


async def test_thread_detail_includes_saved_lists(client, services):
    await client.post("/api/v1/bots", json={"handle": "eng", "name": "Engineer", "provider": "openai", "model": "m"})
    t = (await client.post("/api/v1/threads", json={"title": "Work", "handles": ["eng"]})).json()
    async with services.session_factory() as s:
        eng = (await s.execute(select(Actor).where(Actor.handle == "eng"))).scalar_one()
        s.add(ThreadTodoList(thread_id=t["id"], actor_id=eng.id, items=PLAN))
        await s.commit()

    d = (await client.get(f"/api/v1/threads/{t['id']}")).json()
    assert d["todos"] == [{"actor_id": eng.id, "handle": "eng", "todos": PLAN}]

    assert (await client.delete(f"/api/v1/threads/{t['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/threads/{t['id']}")).status_code == 404
    async with services.session_factory() as s:     # a soft delete keeps the list for investigation
        assert len((await s.execute(select(ThreadTodoList))).scalars().all()) == 1


async def test_migration_creates_the_todo_list_table(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("thread_todo_lists")})
        fks = await conn.run_sync(lambda c: inspect(c).get_foreign_keys("thread_todo_lists"))
        uniques = await conn.run_sync(lambda c: inspect(c).get_unique_constraints("thread_todo_lists"))
    await engine.dispose()
    assert cols == {"id", "thread_id", "actor_id", "items", "created_at", "updated_at"}
    assert {(fk["referred_table"], fk["options"].get("ondelete")) for fk in fks} == {
        ("threads", "CASCADE"), ("actors", "CASCADE")}
    assert [u["column_names"] for u in uniques] == [["thread_id", "actor_id"]]
