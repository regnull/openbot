"""Lazy MCP tools: bound to the agent, offered to the model only after load_tools."""

from langchain_core.tools import tool

from openbot.db.models import Run
from openbot.runtime.tool_loading import deferred_tools_section, resolve_names, search_tools
from tests.fakes import ScriptedChatModel, ai, call
from tests.test_runner import get, make

calls: list[str] = []


@tool("linear__get_issue", description="Retrieve a Linear issue by its id or identifier.")
def get_issue(id: str) -> str:
    calls.append(f"get_issue:{id}")
    return f"issue {id}: fix the login page"


@tool("linear__save_comment", description="Create or update a comment on a Linear issue.")
def save_comment(issue: str, body: str) -> str:
    calls.append(f"save_comment:{issue}")
    return "saved"


DEFERRED = {t.name: t for t in (get_issue, save_comment)}
MCP = ["linear__get_issue", "linear__save_comment"]


def test_search_ranks_name_matches_over_description_matches():
    assert search_tools(DEFERRED, "comment") == ["linear__save_comment"]
    assert search_tools(DEFERRED, "issue")[0] == "linear__get_issue"  # in both names; first wins ties
    assert search_tools(DEFERRED, "zzz") == [] and search_tools(DEFERRED, "") == []


def test_names_resolve_exactly_or_by_unique_suffix():
    assert resolve_names(DEFERRED, ["linear__get_issue", "save_comment", "nope"]) == (
        ["linear__get_issue", "linear__save_comment"],
        ["nope"],
    )


def test_the_prompt_section_lists_names_by_server_without_schemas():
    section = deferred_tools_section(MCP)
    assert section.startswith("# Tools to load on demand")
    assert "- linear: get_issue, save_comment" in section
    assert "Retrieve a Linear issue" not in section


def _text(content) -> str:
    return content if isinstance(content, str) else " ".join(b["text"] for b in content)


def _result(call_id: str, model_call: int):
    """The tool message for `call_id` as the model saw it on model call `model_call` (0-based)."""
    return next(m for m in ScriptedChatModel.seen[model_call] if getattr(m, "tool_call_id", None) == call_id)


async def _run(settings, script, **settings_overrides):
    for k, v in settings_overrides.items():
        setattr(settings, k, v)
    services, _eng, _t, run = await make(settings, {"eng": script}, tool_names=["read_file", *MCP])
    for t in DEFERRED.values():
        services.registry.register(t, source="mcp:linear")
    calls.clear()
    ScriptedChatModel.bound.clear()
    ScriptedChatModel.seen.clear()
    await services.runner.execute(run.id)
    assert (await get(services, Run, run.id)).status == "completed"
    return services


async def test_mcp_tools_are_offered_only_after_load_tools(settings):
    await _run(
        settings,
        [
            ai(tool_calls=[call("load_tools", "l1", names=["linear__get_issue"])]),
            ai(tool_calls=[call("linear__get_issue", "g1", id="ENG-1")]),
            ai("done"),
        ],
    )
    first, second, third = ScriptedChatModel.bound[:3]
    assert "load_tools" in first and "read_file" in first
    assert not set(MCP) & set(first)
    # Loaded tools go last, so a load does not disturb the cached prefix of earlier definitions.
    assert second[-1] == "linear__get_issue" and "linear__save_comment" not in second
    assert third == second  # the loaded set lasts for the rest of the run
    assert calls == ["get_issue:ENG-1"]

    system_text = _text(ScriptedChatModel.seen[0][0].content)
    assert "# Tools to load on demand" in system_text
    assert "- linear: get_issue, save_comment" in system_text
    tools_line = next(
        line for line in system_text.splitlines() if line.startswith("- Tools available to you:")
    )
    assert "load_tools" in tools_line and "linear__" not in tools_line


async def test_load_tools_finds_tools_by_query(settings):
    await _run(
        settings,
        [ai(tool_calls=[call("load_tools", "l1", query="comment on an issue")]), ai("done")],
    )
    assert "linear__save_comment" in ScriptedChatModel.bound[1]


async def test_calling_an_unloaded_tool_is_refused_but_loads_it(settings):
    """The model knows the names from the prompt and may skip load_tools, guessing the arguments.
    That call does not run; the tool is loaded so the retry sees its real schema."""
    await _run(
        settings,
        [
            ai(tool_calls=[call("linear__get_issue", "g1", id="ENG-1")]),
            ai(tool_calls=[call("linear__get_issue", "g2", id="ENG-1")]),
            ai("done"),
        ],
    )
    assert calls == ["get_issue:ENG-1"]  # only the retry ran
    assert "linear__get_issue" not in ScriptedChatModel.bound[0]
    assert "linear__get_issue" in ScriptedChatModel.bound[1]
    refusal = _result("g1", 1)
    assert refusal.content.startswith("error:") and "was not loaded" in refusal.content


async def test_unknown_names_are_reported(settings):
    await _run(
        settings,
        [ai(tool_calls=[call("load_tools", "l1", names=["linear__nope"])]), ai("done")],
    )
    result = _result("l1", 1)
    assert result.content.startswith("error:") and "Unknown: linear__nope" in result.content
    assert not set(MCP) & set(ScriptedChatModel.bound[1])


async def test_approval_gated_tools_are_never_deferred(settings):
    """Approval runs before the deferred refusal, so a gated tool that had to be loaded would be
    approved, refused, and approved again on the retry."""
    services, eng, _t, _ = await make(
        settings, {"eng": []}, tool_names=MCP, approval_tools=["linear__save_comment"]
    )
    for t in DEFERRED.values():
        services.registry.register(t, source="mcp:linear")
    assert services.runner.deferred_tool_names(eng) == ["linear__get_issue"]


async def test_deferral_can_be_turned_off(settings):
    await _run(settings, [ai("done")], defer_mcp_tools=False)
    assert set(MCP) <= set(ScriptedChatModel.bound[0])
    assert "load_tools" not in ScriptedChatModel.bound[0]
