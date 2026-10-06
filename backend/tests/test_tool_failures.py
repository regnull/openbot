"""Failed tool calls are recorded as failures, and a run stuck repeating one is stopped with its error."""
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool, ToolException
from sqlalchemy import select

from openbot.db.models import ActivityLog, Run
from openbot.mcp.manager import _wrap
from openbot.runtime.tool_failures import (
    REPEAT_CALL_NOTE,
    REPEAT_NOTE,
    ToolFailureMiddleware,
    is_failure,
)
from tests.fakes import ai, call
from tests.test_runner import events, get, make, messages


def _missing_file_loop(n: int):
    return [ai(tool_calls=[call("read_file", cid=f"c{i}", path="nope.txt")]) for i in range(n)]


async def test_error_results_are_marked_as_errors(settings):
    services, _eng, _t, run = await make(settings, {"eng": _missing_file_loop(1) + [ai("done")]}, tool_names=["read_file"])
    await services.runner.execute(run.id)
    [result] = [e for e in await events(services, run.id) if e.type == "tool_result"]
    assert result.payload["status"] == "error" and result.payload["content"].startswith("error:")
    async with services.session_factory() as s:
        levels = (await s.execute(select(ActivityLog.level).where(ActivityLog.run_id == run.id,
                                                                  ActivityLog.event == "run.tool_result"))).scalars().all()
    assert levels == ["warning"]


async def test_repeating_an_identical_failure_stops_the_run_with_the_error(settings):
    settings.max_model_calls_per_run = 20
    services, _eng, t, run = await make(settings, {"eng": _missing_file_loop(10) + [ai("never reached")]}, tool_names=["read_file"])
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "completed"
    results = [e for e in await events(services, run.id) if e.type == "tool_result"]
    assert len(results) == 3
    assert REPEAT_NOTE not in results[0].payload["content"] and REPEAT_NOTE in results[1].payload["content"]
    last = (await messages(services, t.id))[-1].content
    assert last.startswith("Stopped: `read_file` failed 3 times") and "nope.txt" in last and "error:" in last


async def test_changing_the_arguments_is_not_a_repeat(settings):
    settings.max_model_calls_per_run = 20
    script = [ai(tool_calls=[call("read_file", cid=f"c{i}", path=f"nope{i}.txt")]) for i in range(4)] + [ai("gave up")]
    services, _eng, t, run = await make(settings, {"eng": script}, tool_names=["read_file"])
    await services.runner.execute(run.id)
    assert (await messages(services, t.id))[-1].content == "gave up"


async def test_the_stop_can_be_turned_off(settings):
    settings.max_repeated_tool_failures = 0
    settings.max_model_calls_per_run = 4
    services, _eng, t, run = await make(settings, {"eng": _missing_file_loop(10)}, tool_names=["read_file"])
    await services.runner.execute(run.id)
    assert [e.type for e in await events(services, run.id)].count("tool_call") == 4
    assert "limit" in (await messages(services, t.id))[-1].content.lower()


def test_is_failure():
    assert is_failure(ToolMessage("error: boom", tool_call_id="c"))
    assert is_failure(ToolMessage("anything", tool_call_id="c", status="error"))
    assert not is_failure(ToolMessage("no error: here", tool_call_id="c"))


def test_the_stop_only_counts_identical_failures():
    mw = ToolFailureMiddleware(max_repeats=2)
    first = AIMessage("", tool_calls=[call("t", cid="a", x=1)])
    second = AIMessage("", tool_calls=[call("t", cid="b", x=1)])
    same = [first, ToolMessage("error: e", tool_call_id="a"), second, ToolMessage("error: e" + REPEAT_NOTE, tool_call_id="b")]
    assert mw._check({"messages": same})["jump_to"] == "end"
    other_error = [first, ToolMessage("error: e", tool_call_id="a"), second, ToolMessage("error: f", tool_call_id="b")]
    assert mw._check({"messages": other_error}) is None


def test_repeated_successful_calls_are_warned_then_stopped():
    mw = ToolFailureMiddleware(max_repeats=3)
    calls = [AIMessage("", tool_calls=[call("t", cid=str(i), x=1)]) for i in range(1, 5)]
    messages = [calls[0], ToolMessage("one", tool_call_id="1"), calls[1], ToolMessage("two", tool_call_id="2")]
    request = type("Request", (), {"tool_call": call("t", cid="3", x=1), "state": {"messages": messages}})()
    result = mw._mark(request, ToolMessage("three", tool_call_id="3"))
    assert REPEAT_CALL_NOTE in result.content
    continued = messages + [calls[2], result, calls[3], ToolMessage("four", tool_call_id="4")]
    assert mw._check({"messages": continued})["jump_to"] == "end"


def test_repeated_call_sequence_resets_for_a_different_tool_or_arguments():
    mw = ToolFailureMiddleware(max_repeats=3)
    first = AIMessage("", tool_calls=[call("t", cid="a", x=1)])
    second = AIMessage("", tool_calls=[call("t", cid="b", x=2)])
    messages = [first, ToolMessage("one", tool_call_id="a"), second, ToolMessage("two", tool_call_id="b")]
    assert mw._check({"messages": messages}) is None


async def test_mcp_server_errors_reach_the_model_as_error_results():
    async def bad(x: str):
        raise ToolException("`statusUpdateType` is only valid together with `statusUpdateId`")

    tool = _wrap(StructuredTool.from_function(coroutine=bad, name="t", description="t", handle_tool_error=True), "linear__t", 400)
    out = await tool.ainvoke({"x": "1"})
    assert is_failure(ToolMessage(out, tool_call_id="c"))
