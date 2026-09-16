from langgraph.types import Command
from sqlalchemy import select

from openbot.db.models import InboxItem, Message, Run, RunEvent
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.runtime.runner import Runner, normalize_interrupt
from tests.conftest import build_test_services
from tests.factories import bot_actor
from tests.fakes import ScriptedChatModel, ai, call


async def make(settings, scripts, *, working_directory=None, **profile):
    services = await build_test_services(settings, scripts)
    services.actors = None            # drive the runner directly in these tests
    services.runner = Runner(services)
    async with services.session_factory() as s:
        eng, rev = bot_actor("eng", description="builds", **profile), bot_actor("rev", description="reviews")
        s.add_all([eng, rev])
        await s.commit()
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you,
                                working_directory=working_directory)
        res = await post_message(services, s, thread_id=t.id, sender=you, content="please build it")
        item = res.items[0]
        run = Run(actor_id=eng.id, thread_id=t.id)
        s.add(run)
        await s.flush()
        item.run_id, item.status = run.id, "processing"
        await s.commit()
    return services, eng, t, run


async def get(services, model, id_):
    async with services.session_factory() as s:
        return await s.get(model, id_)


async def messages(services, thread_id):
    async with services.session_factory() as s:
        return (await s.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at))).scalars().all()


async def events(services, run_id):
    async with services.session_factory() as s:
        return (await s.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq))).scalars().all()


def test_normalize_interrupt():
    assert normalize_interrupt({"kind": "question", "question": "q"}) == {"kind": "question", "question": "q"}
    v = normalize_interrupt({"action_requests": [{"name": "run_shell", "args": {"command": "ls"}, "description": "d"}]})
    assert v == {"kind": "approval", "actions": [{"name": "run_shell", "args": {"command": "ls"}}]}
    assert normalize_interrupt("raw") == {"kind": "question", "question": "raw"}


async def test_simple_reply_and_handoff(settings):
    ScriptedChatModel.seen.clear()
    services, eng, t, run = await make(settings, {"eng": [ai("Built it. @rev please review")]})
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "completed" and run.finished_at is not None
    msgs = await messages(services, t.id)
    assert msgs[-1].sender_actor_id == eng.id and msgs[-1].hop == 1 and msgs[-1].run_id == run.id
    async with services.session_factory() as s:
        rev_items = (await s.execute(select(InboxItem).where(InboxItem.message_id == msgs[-1].id, InboxItem.kind == "message"))).scalars().all()
    assert {i.actor_id for i in rev_items} >= {msgs[-1].mentions[0]}
    sent = ScriptedChatModel.seen[0]
    assert sent[0].type == "system" and "@rev" in sent[0].content and "[You]: please build it" in sent[-1].content
    assert [e.type for e in await events(services, run.id)] == ["text", "message"]


async def test_runner_uses_thread_working_directory_for_tools(settings):
    (settings.workspace_root / "project").mkdir(parents=True)
    ScriptedChatModel.seen.clear()
    services, _eng, _t, run = await make(settings, {"eng": [ai(tool_calls=[call("run_shell", command="pwd")]), ai("done")]},
                                         working_directory="project", tool_names=["run_shell"])
    await services.runner.execute(run.id)

    assert str(settings.workspace_root / "project") in ScriptedChatModel.seen[0][0].content
    assert any(e.type == "tool_result" and str(settings.workspace_root / "project") in e.payload["content"]
               for e in await events(services, run.id))


async def test_tool_call_events(settings):
    settings.tools_dir.mkdir(parents=True)
    (settings.tools_dir / "p.py").write_text('from langchain.tools import tool\n@tool\ndef ping() -> str:\n    """Ping."""\n    return "pong"\n')
    services, _eng, _t, run = await make(settings, {"eng": [ai(tool_calls=[call("ping")]), ai("pong received")]}, tool_names=["ping"])
    await services.runner.execute(run.id)
    ev = await events(services, run.id)
    assert [e.type for e in ev] == ["tool_call", "tool_result", "text", "message"]
    assert ev[0].payload["name"] == "ping" and ev[1].payload["content"] == "pong"


async def test_ask_human_and_resume(settings):
    services, _eng, _t, run = await make(settings, {"eng": [ai(tool_calls=[call("ask_human", question="Merge?")]), ai("Merging as you said.")]})
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "waiting_human" and run.interrupt == {"kind": "question", "question": "Merge?"}
    async with services.session_factory() as s:
        qs = (await s.execute(select(InboxItem).where(InboxItem.kind == "question"))).scalars().all()
    assert len(qs) == 1 and qs[0].payload["interrupt"]["question"] == "Merge?" and qs[0].run_id == run.id
    await services.runner.execute(run.id, resume=Command(resume="yes"))
    run = await get(services, Run, run.id)
    assert run.status == "completed" and run.interrupt is None
    ev = await events(services, run.id)
    assert [e.type for e in ev] == ["tool_call", "interrupt", "resumed", "tool_result", "text", "message"]
    assert "yes" in ev[3].payload["content"]


async def test_tool_approval(settings):
    services, _eng, _t, run = await make(settings, {"eng": [ai(tool_calls=[call("run_shell", command="echo hi")]), ai("done")]},
                                       tool_names=["run_shell"], approval_tools=["run_shell"])
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "waiting_human" and run.interrupt["kind"] == "approval" and run.interrupt["actions"][0]["name"] == "run_shell"
    await services.runner.execute(run.id, resume=Command(resume={"decisions": [{"type": "approve"}]}))
    run = await get(services, Run, run.id)
    assert run.status == "completed"
    assert any(e.type == "tool_result" and "hi" in e.payload["content"] for e in await events(services, run.id))


async def test_failure_posts_system_message(settings):
    services, eng, t, run = await make(settings, {"eng": [RuntimeError("provider down")]})
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "failed" and "provider down" in run.error
    msgs = await messages(services, t.id)
    assert msgs[-1].sender_kind == "system" and "@eng failed" in msgs[-1].content
    async with services.session_factory() as s:
        bot_items = (await s.execute(select(InboxItem).where(InboxItem.actor_id == eng.id))).scalars().all()
    assert len(bot_items) == 1  # the system message did not create new work for the bot


async def test_failure_mid_stream_records_error_after_earlier_events(settings):
    settings.tools_dir.mkdir(parents=True)
    (settings.tools_dir / "p.py").write_text('from langchain.tools import tool\n@tool\ndef ping() -> str:\n    """Ping."""\n    return "pong"\n')
    services, _eng, t, run = await make(settings, {"eng": [ai(tool_calls=[call("ping")]), RuntimeError("provider down")]},
                                       tool_names=["ping"])
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "failed" and "provider down" in run.error
    ev = await events(services, run.id)
    assert [e.type for e in ev] == ["tool_call", "tool_result", "error"]
    assert [e.seq for e in ev] == [0, 1, 2]
    msgs = await messages(services, t.id)
    assert msgs[-1].sender_kind == "system" and "@eng failed" in msgs[-1].content


async def test_failure_status_survives_a_broken_error_event(settings, monkeypatch):
    services, _eng, t, run = await make(settings, {"eng": [RuntimeError("provider down")]})

    async def boom(*_a, **_k):
        raise RuntimeError("run_events table is gone")

    monkeypatch.setattr(Runner, "_record", boom)
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "failed" and "provider down" in run.error and run.finished_at is not None
    assert not await events(services, run.id)
    msgs = await messages(services, t.id)  # bookkeeping continued past the broken step
    assert msgs[-1].sender_kind == "system" and "@eng failed" in msgs[-1].content


async def test_reflection_failure_does_not_fail_a_completed_run(settings):
    services, _eng, t, run = await make(settings, {"eng": [ai("Built it.")]})

    def boom(*_a, **_k):
        raise RuntimeError("reflector exploded")

    services.reflector.schedule = boom
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "completed" and run.error is None
    msgs = await messages(services, t.id)
    assert msgs[-1].sender_kind == "bot" and msgs[-1].content == "Built it."
    assert not [m for m in msgs if m.sender_kind == "system"]
    assert [e.type for e in await events(services, run.id)] == ["text", "message"]


async def test_memory_reflection_scheduled(settings):
    services, _eng, _t, run = await make(settings, {"eng": [ai("ok")]})
    scheduled = []
    services.reflector.schedule = lambda bot, msgs: scheduled.append((bot.handle, len(msgs)))
    await services.runner.execute(run.id)
    assert scheduled and scheduled[0][0] == "eng" and scheduled[0][1] >= 2



async def test_langsmith_id_is_the_pinned_trace_root(settings, monkeypatch):
    """The run card must link the `bot:<handle>` root. Under LangGraph streaming the runs that
    collect_runs() returns all look parentless in memory (LangSmith only links them server-side
    from dotted_order), so the root id is pinned in the config up front and stored from there."""
    from openbot.runtime import runner as runner_mod

    seen: dict = {}
    original = Runner._stream

    async def spy(self, agent, inputs, config, ctx, run, seq):
        seen["config_run_id"] = config.get("run_id")
        return await original(self, agent, inputs, config, ctx, run, seq)

    monkeypatch.setattr(Runner, "_stream", spy)
    # collect_runs() yields nothing without a tracer, and then no LangSmith id may be stored.
    monkeypatch.setattr(runner_mod, "collect_runs", _collecting(["nested-child-run"]))

    services, _eng, _t, run = await make(settings, {"eng": [ai("done")]})
    await services.runner.execute(run.id)

    run = await get(services, Run, run.id)
    assert run.langsmith_run_id == str(seen["config_run_id"]) != "nested-child-run"


async def test_no_langsmith_id_when_nothing_is_traced(settings, monkeypatch):
    from openbot.runtime import runner as runner_mod

    monkeypatch.setattr(runner_mod, "collect_runs", _collecting([]))
    services, _eng, _t, run = await make(settings, {"eng": [ai("done")]})
    await services.runner.execute(run.id)
    assert (await get(services, Run, run.id)).langsmith_run_id is None


def _collecting(traced):
    from contextlib import contextmanager

    @contextmanager
    def fake():
        yield type("CB", (), {"traced_runs": traced})()

    return fake


async def test_runner_logs_run_context_and_tool_activity(settings, caplog):
    import logging
    caplog.set_level(logging.DEBUG, logger="openbot")
    (settings.workspace_root / "project").mkdir(parents=True)
    services, eng, _t, run = await make(settings, {"eng": [ai(tool_calls=[call("list_files", path=".")]), ai("done")]},
                                        working_directory="project", tool_names=["list_files"])
    await services.runner.execute(run.id)

    lines = [r.getMessage() for r in caplog.records if r.name.startswith("openbot.runtime.runner")]
    start = next(l for l in lines if l.startswith(f"run {run.id} started"))
    assert "bot=@eng" in start and "working_directory=project" in start
    assert f"tool_root={(settings.workspace_root / 'project').resolve()}" in start
    assert f"model={eng.bot.provider}/{eng.bot.model}" in start
    assert any(l.startswith(f"run {run.id} tool_call list_files") and '"path": "."' in l for l in lines)
    assert any(l.startswith(f"run {run.id} tool_result list_files") and "status=success" in l for l in lines)
    assert any(l.startswith(f"run {run.id} completed") for l in lines)
    debug = [r for r in caplog.records if r.levelno == logging.DEBUG and "system prompt" in r.getMessage()]
    assert debug and str((settings.workspace_root / "project").resolve()) in debug[0].getMessage()
