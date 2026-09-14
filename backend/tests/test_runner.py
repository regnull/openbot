from langgraph.types import Command
from sqlalchemy import select

from openbot.db.models import InboxItem, Message, Run, RunEvent
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.runtime.runner import Runner, normalize_interrupt
from tests.conftest import build_test_services
from tests.factories import bot_actor
from tests.fakes import ScriptedChatModel, ai, call


async def make(settings, scripts, **profile):
    services = await build_test_services(settings, scripts)
    services.actors = None            # drive the runner directly in these tests
    services.runner = Runner(services)
    async with services.session_factory() as s:
        eng, rev = bot_actor("eng", description="builds", **profile), bot_actor("rev", description="reviews")
        s.add_all([eng, rev])
        await s.commit()
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you)
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


async def test_memory_reflection_scheduled(settings):
    services, _eng, _t, run = await make(settings, {"eng": [ai("ok")]})
    scheduled = []
    services.reflector.schedule = lambda bot, msgs: scheduled.append((bot.handle, len(msgs)))
    await services.runner.execute(run.id)
    assert scheduled and scheduled[0][0] == "eng" and scheduled[0][1] >= 2
