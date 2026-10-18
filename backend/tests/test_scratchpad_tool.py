"""The scratchpad tool: one per-bot notepad in the database, injected into the system prompt."""

import pytest_asyncio
from langchain.tools import ToolRuntime

from openbot.db.models import Actor, BotScratchpad, Run, Thread
from openbot.runtime.delivery import create_thread, human_actor
from openbot.runtime.prompt import build_system_prompt_parts
from openbot.tools.builtin.scratchpad import (
    MAX_SCRATCHPAD_CHARS,
    load_scratchpad,
    scratchpad,
)
from openbot.tools.context import RunContext
from tests.factories import bot_actor
from tests.test_runner import get, make


@pytest_asyncio.fixture
async def _no_actor_runs(services):
    """Nothing here needs a run; stop the actor system so no background run races the assertions."""
    await services.actors.stop()


def rt(services, bot, thread_id):
    ctx = RunContext(
        bot.id, bot.handle, bot.name, thread_id, "run", services.settings.workspace_root, services
    )
    return ToolRuntime(
        context=ctx,
        store=services.store,
        state={},
        tool_call_id="c",
        config={},
        stream_writer=lambda *_: None,
    )


async def setup(services):
    async with services.session_factory() as s:
        eng, rev = bot_actor("eng"), bot_actor("rev")
        s.add_all([eng, rev])
        await s.commit()
        you = await human_actor(s)
        t1 = await create_thread(services, s, title="t1", handles=["eng", "rev"], created_by=you)
        t2 = await create_thread(services, s, title="t2", handles=["eng"], created_by=you)
        return eng, rev, t1, t2


async def saved(services, actor_id):
    async with services.session_factory() as s:
        return await load_scratchpad(s, actor_id)


async def test_read_reports_an_empty_pad_and_write_replaces(services, _no_actor_runs):
    eng, _rev, t1, _t2 = await setup(services)

    out = await scratchpad.ainvoke({"action": "read", "runtime": rt(services, eng, t1.id)})
    assert out == "Scratchpad is empty."

    out = await scratchpad.ainvoke(
        {
            "action": "write",
            "content": "branch: feat/x\nPR 12 open",
            "runtime": rt(services, eng, t1.id),
        }
    )
    assert out.startswith("Scratchpad replaced (25 characters). Saved")
    assert await saved(services, eng.id) == "branch: feat/x\nPR 12 open"

    out = await scratchpad.ainvoke(
        {"action": "write", "content": "fresh", "runtime": rt(services, eng, t1.id)}
    )
    assert out.startswith("Scratchpad replaced (5 characters).")
    assert await saved(services, eng.id) == "fresh"

    out = await scratchpad.ainvoke({"action": "clear", "runtime": rt(services, eng, t1.id)})
    assert out == "Scratchpad cleared."
    assert await saved(services, eng.id) == ""
    out = await scratchpad.ainvoke({"action": "clear", "runtime": rt(services, eng, t1.id)})
    assert out == "Scratchpad is already empty."


async def test_a_save_without_content_is_refused_not_a_wipe(services, _no_actor_runs):
    """A model that drops `content` must not erase the pad behind a success message: the run that
    surfaced this re-sent {"action": "write"} until the repeated-call guard stopped it."""
    eng, _rev, t1, _t2 = await setup(services)
    await scratchpad.ainvoke(
        {"action": "write", "content": "keep me", "runtime": rt(services, eng, t1.id)}
    )
    for args in ({"action": "write"}, {"action": "write", "content": ""}, {"action": "append"}):
        out = await scratchpad.ainvoke({**args, "runtime": rt(services, eng, t1.id)})
        assert out.startswith("error:") and "unchanged" in out and "action=clear" in out
        assert await saved(services, eng.id) == "keep me"


async def test_an_identical_save_says_so_instead_of_acking_a_change(services, _no_actor_runs):
    eng, _rev, t1, _t2 = await setup(services)
    await scratchpad.ainvoke(
        {"action": "write", "content": "same notes", "runtime": rt(services, eng, t1.id)}
    )
    out = await scratchpad.ainvoke(
        {"action": "write", "content": "same notes", "runtime": rt(services, eng, t1.id)}
    )
    assert out.startswith("Scratchpad unchanged") and "do not repeat" in out
    assert await saved(services, eng.id) == "same notes"


async def test_append_joins_without_eating_lines(services, _no_actor_runs):
    eng, _rev, t1, _t2 = await setup(services)
    await scratchpad.ainvoke(
        {"action": "write", "content": "part one", "runtime": rt(services, eng, t1.id)}
    )
    out = await scratchpad.ainvoke(
        {"action": "append", "content": "part two", "runtime": rt(services, eng, t1.id)}
    )
    assert out.startswith("Scratchpad appended to (17 characters).")
    assert await saved(services, eng.id) == "part one\npart two"

    await scratchpad.ainvoke(
        {"action": "write", "content": "line\n", "runtime": rt(services, eng, t1.id)}
    )
    await scratchpad.ainvoke(
        {"action": "append", "content": "next", "runtime": rt(services, eng, t1.id)}
    )
    assert await saved(services, eng.id) == "line\nnext"  # no doubled newline


async def test_pads_are_per_bot_across_threads(services, _no_actor_runs):
    """Keyed by bot, not thread: notes made in one conversation show up in another."""
    eng, rev, t1, t2 = await setup(services)
    await scratchpad.ainvoke(
        {"action": "write", "content": "eng notes", "runtime": rt(services, eng, t1.id)}
    )
    await scratchpad.ainvoke(
        {"action": "write", "content": "rev notes", "runtime": rt(services, rev, t1.id)}
    )

    assert await saved(services, eng.id) == "eng notes"
    assert await saved(services, rev.id) == "rev notes"
    assert (
        await scratchpad.ainvoke({"action": "read", "runtime": rt(services, eng, t2.id)})
        == "eng notes"
    )
    assert (
        await scratchpad.ainvoke({"action": "read", "runtime": rt(services, rev, t2.id)})
        == "rev notes"
    )


async def test_pads_survive_new_sessions(services, _no_actor_runs):
    """The table is keyed by actor only, so a fresh session (as after a restart) sees the same row."""
    eng, _rev, t1, _t2 = await setup(services)
    await scratchpad.ainvoke(
        {"action": "write", "content": "carried over", "runtime": rt(services, eng, t1.id)}
    )
    async with services.session_factory() as s:
        assert await load_scratchpad(s, eng.id) == "carried over"


async def test_oversized_writes_are_rejected_with_guidance(services, _no_actor_runs):
    eng, _rev, t1, _t2 = await setup(services)
    out = await scratchpad.ainvoke(
        {
            "action": "write",
            "content": "x" * (MAX_SCRATCHPAD_CHARS + 1),
            "runtime": rt(services, eng, t1.id),
        }
    )
    assert out.startswith("error:")
    assert "pruned" in out and "action=write" in out
    assert await saved(services, eng.id) == ""

    await scratchpad.ainvoke(
        {
            "action": "write",
            "content": "a" * MAX_SCRATCHPAD_CHARS,
            "runtime": rt(services, eng, t1.id),
        }
    )
    out = await scratchpad.ainvoke(
        {"action": "append", "content": "more", "runtime": rt(services, eng, t1.id)}
    )
    assert out.startswith("error:")
    assert await saved(services, eng.id) == "a" * MAX_SCRATCHPAD_CHARS


def test_the_scratchpad_goes_in_the_dynamic_prompt_only():
    bot = bot_actor("eng")
    bot.id = "e"
    kw = {
        "bot": bot,
        "all_bots": [bot],
        "participants": ["You"],
        "memories": [],
        "workspace_root": "/w",
        "older_count": 0,
        "tool_names": ["scratchpad"],
    }
    stable, dynamic = build_system_prompt_parts(**kw, scratchpad="step 1 done\nnow: write tests")
    assert "# Your scratchpad" in dynamic and "now: write tests" in dynamic
    assert "# Your scratchpad" not in stable
    # The section is a run-start snapshot; it says so, or a bot re-saves notes it already saved.
    assert "Snapshot from the start of this run" in dynamic
    empty_dynamic = build_system_prompt_parts(**kw, scratchpad="")[1]
    assert "# Your scratchpad" in empty_dynamic and "nothing saved yet" in empty_dynamic
    assert "Snapshot from the start of this run" in empty_dynamic
    assert "# Your scratchpad" not in build_system_prompt_parts(**kw)[1]


async def test_the_next_run_sees_the_saved_pad(settings):
    """The pad outlives the run that wrote it: the next run's system prompt carries it."""
    from tests.fakes import ai, call

    script = [
        ai(tool_calls=[call("scratchpad", action="write", content="found it in runner.py:624")]),
        ai("on it"),
    ]
    services, eng, t, run = await make(settings, {"eng": script}, tool_names=["scratchpad"])
    await services.runner.execute(run.id)
    assert (await get(services, Run, run.id)).status == "completed"

    async with services.session_factory() as s:
        bot, thread, again = (
            await s.get(Actor, eng.id),
            await s.get(Thread, t.id),
            await s.get(Run, run.id),
        )
    prompt, _inputs, _hop = await services.runner._prepare(bot, thread, again)
    dynamic = prompt.content[1]["text"]
    assert "# Your scratchpad" in dynamic and "runner.py:624" in dynamic


async def test_a_bot_without_the_tool_still_gets_its_saved_pad_injected(settings):
    """Injection is per-bot, not gated on the tool list: losing the tool drops the tool, not the notes."""
    services, eng, t, run = await make(settings, {"eng": []}, tool_names=["run_shell"])
    async with services.session_factory() as s:
        s.add(BotScratchpad(actor_id=eng.id, content="kept notes"))
        await s.commit()
        bot, thread, again = (
            await s.get(Actor, eng.id),
            await s.get(Thread, t.id),
            await s.get(Run, run.id),
        )
    prompt, _inputs, _hop = await services.runner._prepare(bot, thread, again)
    assert (
        "# Your scratchpad" in prompt.content[1]["text"]
        and "kept notes" in prompt.content[1]["text"]
    )


async def test_every_agent_carries_the_tool_even_when_the_profile_omits_it(services, monkeypatch):
    """Bots whose saved tool list predates the scratchpad (or omits it) still get the tool: the runner
    always resolves it, because its saved content is injected into every run's system prompt."""
    from openbot.runtime import runner as runner_mod

    captured = {}

    def fake_create_agent(model, tools, **kwargs):
        captured["tools"] = tools
        return object()

    monkeypatch.setattr(runner_mod, "create_agent", fake_create_agent)
    bot = bot_actor("old", tool_names=[])
    bot.id = "o1"
    services.runner._build_agent(bot, "system prompt")
    assert "scratchpad" in [t.name for t in captured["tools"]]


async def test_boot_grants_the_scratchpad_to_existing_bots(services):
    """start_background wires the one-time grant: bots whose rows predate the tool gain it at boot,
    the flag is recorded, and the profile-less system actor (cron) is skipped without a crash."""
    from openbot.db.models import AppSetting
    from openbot.main import start_background

    eng, rev, _t1, _t2 = await setup(services)
    async with services.session_factory() as s:
        (await s.get(Actor, eng.id)).bot.tool_names = ["run_shell"]
        (await s.get(Actor, rev.id)).bot.tool_names = ["memory_search"]
        await s.commit()

    await start_background(services)

    async with services.session_factory() as s:
        assert (await s.get(Actor, eng.id)).bot.tool_names == ["run_shell", "scratchpad"]
        assert (await s.get(Actor, rev.id)).bot.tool_names == ["memory_search", "scratchpad"]
        assert await s.get(AppSetting, "_scratchpad_grant_done") is not None


async def test_the_grant_never_runs_twice(services):
    """The flag makes the grant one-shot: a bot a human later edits to drop the tool is not
    re-granted on the next boot."""
    from openbot.seed import grant_scratchpad_to_existing_bots

    eng, _rev, _t1, _t2 = await setup(services)
    async with services.session_factory() as s:
        eng.bot.tool_names = ["run_shell"]
        await s.commit()

    await grant_scratchpad_to_existing_bots(services)
    async with services.session_factory() as s:
        (await s.get(Actor, eng.id)).bot.tool_names = ["run_shell"]
        await s.commit()

    await grant_scratchpad_to_existing_bots(services)

    async with services.session_factory() as s:
        assert (await s.get(Actor, eng.id)).bot.tool_names == ["run_shell"]


async def test_the_grant_skips_actors_without_a_bot_profile(services):
    """Only kind="bot" rows have profiles; a system actor without one must not crash the grant."""
    from openbot.db.models import AppSetting
    from openbot.seed import grant_scratchpad_to_existing_bots

    eng, _rev, _t1, _t2 = await setup(services)
    async with services.session_factory() as s:
        s.add(Actor(kind="system", handle="extra", name="Extra"))
        await s.commit()

    await grant_scratchpad_to_existing_bots(services)

    async with services.session_factory() as s:
        assert "scratchpad" in (await s.get(Actor, eng.id)).bot.tool_names
        assert await s.get(AppSetting, "_scratchpad_grant_done") is not None
