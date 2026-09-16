"""Controls that keep a run's token bill bounded: capped tool output with line-range reads, a per-run
model-call limit, clearing of old tool results, per-run usage accounting, and the seeded team's
division of labour."""
import logging
from pathlib import Path

from langchain.tools import ToolRuntime
from sqlalchemy import inspect, select

from openbot.db.models import Actor, Run
from openbot.db.session import make_engine, run_migrations
from openbot.runtime.runner import CLEARED_TOOL_RESULT
from openbot.seed import DEMO_BOTS, seed_demo_bots
from openbot.tools.builtin.files import read_file
from openbot.tools.builtin.shell import run_shell
from openbot.tools.builtin.workspace import cap
from openbot.tools.context import RunContext
from tests.fakes import ScriptedChatModel, ai, call
from tests.test_runner import events, get, make, messages


def rt(root: Path, cap_chars: int = 8000) -> ToolRuntime:
    root.mkdir(parents=True, exist_ok=True)
    ctx = RunContext("b", "bot", "Bot", "t", "r", root.resolve(), None, tool_output_cap=cap_chars)
    return ToolRuntime(context=ctx, store=None, state={}, tool_call_id="c", config={}, stream_writer=lambda *_: None)


# --- tool output ------------------------------------------------------------------------------------

def test_cap_keeps_head_and_tail_and_says_how_much_was_dropped():
    text = "".join(f"line{i:04d}\n" for i in range(1000))
    out = cap(text, 800, hint="use a range")
    assert len(out) < 1000
    assert out.startswith("line0000\n") and out.endswith("line0999\n")
    assert "[truncated" in out and "use a range" in out and f"of {len(text)}" in out
    assert cap("short", 800) == "short"


async def test_read_file_supports_line_ranges(tmp_path):
    (tmp_path / "f.txt").write_text("\n".join(f"L{i}" for i in range(1, 51)))
    r = rt(tmp_path)
    assert await read_file.ainvoke({"path": "f.txt", "start_line": 10, "end_line": 12, "runtime": r}) == "lines 10-12 of 50:\nL10\nL11\nL12"
    assert (await read_file.ainvoke({"path": "f.txt", "start_line": 49, "runtime": r})).startswith("lines 49-50 of 50:")
    assert (await read_file.ainvoke({"path": "f.txt", "end_line": 2, "runtime": r})) == "lines 1-2 of 50:\nL1\nL2"
    assert "error: no lines in range" in await read_file.ainvoke({"path": "f.txt", "start_line": 60, "runtime": r})


async def test_tools_honour_the_context_output_cap(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 5000)
    small = rt(tmp_path, cap_chars=1000)
    out = await read_file.ainvoke({"path": "big.txt", "runtime": small})
    assert len(out) < 1200 and "start_line/end_line" in out
    out = await run_shell.ainvoke({"command": "python3 -c \"print('y'*5000)\"", "runtime": small})
    assert len(out) < 1200 and "[truncated" in out and out.startswith("exit code: 0")


# --- runner: limits, context editing, usage ----------------------------------------------------------

def _shell_loop(n: int):
    return [ai(tool_calls=[call("run_shell", cid=f"c{i}", command=f"echo step{i}")]) for i in range(n)]


async def test_model_call_limit_ends_the_run_with_a_notice(settings):
    settings.max_model_calls_per_run = 3
    services, _eng, t, run = await make(settings, {"eng": _shell_loop(10) + [ai("never reached")]}, tool_names=["run_shell"])
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "completed"
    assert [e.type for e in await events(services, run.id)].count("tool_call") == 3
    last = (await messages(services, t.id))[-1]
    assert "limit" in last.content.lower()


async def test_bot_model_settings_can_lower_the_model_call_limit(settings):
    settings.max_model_calls_per_run = 40
    services, _eng, t, run = await make(settings, {"eng": _shell_loop(10) + [ai("never reached")]}, tool_names=["run_shell"],
                                        model_settings={"max_model_calls": 2})
    await services.runner.execute(run.id)
    assert [e.type for e in await events(services, run.id)].count("tool_call") == 2
    assert "limit" in (await messages(services, t.id))[-1].content.lower()


async def test_old_tool_results_are_cleared_once_context_passes_the_trigger(settings):
    settings.context_trigger_tokens = 50   # tiny, so five small tool results are enough to trip it
    ScriptedChatModel.seen.clear()
    services, _eng, _t, run = await make(settings, {"eng": _shell_loop(6) + [ai("done")]}, tool_names=["run_shell"])
    await services.runner.execute(run.id)
    final_prompt = ScriptedChatModel.seen[-1]
    tool_contents = [m.content for m in final_prompt if m.type == "tool"]
    assert tool_contents, "expected tool messages in the final model call"
    assert tool_contents[0] == CLEARED_TOOL_RESULT            # the oldest result was replaced
    assert tool_contents[-1] != CLEARED_TOOL_RESULT           # the most recent ones are kept
    # ...but the run's own event log still has the real output
    real = [e for e in await events(services, run.id) if e.type == "tool_result"]
    assert "step0" in real[0].payload["content"]


async def test_usage_is_summed_logged_and_stored(settings, caplog):
    caplog.set_level(logging.INFO, logger="openbot")
    usage1 = {"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050, "input_token_details": {"cache_read": 800}}
    usage2 = {"input_tokens": 1200, "output_tokens": 30, "total_tokens": 1230}
    services, _eng, _t, run = await make(settings, {"eng": [ai(tool_calls=[call("run_shell", command="echo hi")], usage=usage1),
                                                            ai("done", usage=usage2)]}, tool_names=["run_shell"])
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert (run.prompt_tokens, run.completion_tokens, run.cache_read_tokens, run.total_tokens, run.model_calls) == (2200, 80, 800, 2280, 2)
    lines = [r.getMessage() for r in caplog.records if r.name == "openbot.runtime.runner"]
    assert any(l.startswith(f"run {run.id} model call 1:") and "prompt=1000 (cache_read=800) completion=50" in l for l in lines)
    assert any(l.startswith(f"run {run.id} completed") and "model_calls=2 prompt_tokens=2200 cache_read_tokens=800 completion_tokens=80" in l
               for l in lines)


async def test_usage_stays_null_when_the_model_reports_none(settings):
    services, _eng, _t, run = await make(settings, {"eng": [ai("done")]})
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.prompt_tokens is None and run.model_calls is None


async def test_runs_api_exposes_usage(client, services):
    from openbot.db.models import Thread
    from tests.factories import bot_actor
    async with services.session_factory() as s:
        eng, thread = bot_actor("eng"), Thread(title="t")
        s.add_all([eng, thread])
        await s.flush()
        run = Run(actor_id=eng.id, thread_id=thread.id, status="completed", prompt_tokens=10, completion_tokens=2,
                  cache_read_tokens=5, total_tokens=12, model_calls=1)
        s.add(run)
        await s.commit()
        run_id = run.id
    r = await client.get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert (body["prompt_tokens"], body["completion_tokens"], body["cache_read_tokens"], body["total_tokens"], body["model_calls"]) == (10, 2, 5, 12, 1)


async def test_migration_adds_usage_columns(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("runs")})
    await engine.dispose()
    assert {"prompt_tokens", "completion_tokens", "cache_read_tokens", "total_tokens", "model_calls"} <= cols


# --- seeded team --------------------------------------------------------------------------------------

def test_seeded_division_of_labour():
    bots = {b["handle"]: b for b in DEMO_BOTS}
    assert bots["chief_of_staff"]["tool_names"] == []
    assert bots["chief_of_staff"]["model_settings"] == {"max_model_calls": 6}
    assert "first reply" in bots["chief_of_staff"]["instructions"]
    assert "Do not run the test suite" in bots["reviewer"]["instructions"]
    assert "--name-only" in bots["reviewer"]["instructions"]
    assert "own running the tests" in bots["qa"]["instructions"]
    assert "start_line/end_line" in bots["engineer"]["instructions"]


async def test_seed_persists_model_settings(services):
    services.settings.openrouter_api_key = "k"
    assert await seed_demo_bots(services) == 4
    async with services.session_factory() as s:
        chief = (await s.execute(select(Actor).where(Actor.handle == "chief_of_staff"))).scalar_one()
    assert chief.bot.model_settings == {"max_model_calls": 6}
    assert chief.bot.tool_names == []
    assert services.runner.model_call_limit(chief) == 6


async def test_thread_usage_sums_all_runs(client, services):
    """The thread header shows running totals over every run, finished or not, and treats
    runs that never reported usage as zero."""
    from openbot.db.models import Thread
    from tests.factories import bot_actor
    async with services.session_factory() as s:
        eng, thread, other = bot_actor("eng"), Thread(title="t"), Thread(title="other")
        s.add_all([eng, thread, other])
        await s.flush()
        s.add_all([
            Run(actor_id=eng.id, thread_id=thread.id, status="completed", prompt_tokens=10, completion_tokens=2,
                cache_read_tokens=5, total_tokens=12, model_calls=1),
            Run(actor_id=eng.id, thread_id=thread.id, status="waiting_human", prompt_tokens=100, completion_tokens=20,
                cache_read_tokens=0, total_tokens=120, model_calls=3),
            Run(actor_id=eng.id, thread_id=thread.id, status="queued"),
            Run(actor_id=eng.id, thread_id=other.id, status="completed", prompt_tokens=999, completion_tokens=999,
                cache_read_tokens=999, total_tokens=1998, model_calls=9),
        ])
        await s.commit()
        thread_id = thread.id
    r = await client.get(f"/api/v1/threads/{thread_id}/usage")
    assert r.status_code == 200
    assert r.json() == {"model_calls": 4, "prompt_tokens": 110, "completion_tokens": 22, "cache_read_tokens": 5}


async def test_thread_usage_is_zero_for_thread_without_runs(client, services):
    from openbot.db.models import Thread
    async with services.session_factory() as s:
        thread = Thread(title="t")
        s.add(thread)
        await s.commit()
        thread_id = thread.id
    r = await client.get(f"/api/v1/threads/{thread_id}/usage")
    assert r.status_code == 200
    assert r.json() == {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cache_read_tokens": 0}
    assert (await client.get("/api/v1/threads/nope/usage")).status_code == 404
