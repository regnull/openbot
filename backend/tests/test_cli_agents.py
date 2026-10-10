"""Bots whose provider is a coding agent CLI (#196), run against tests/fake_claude.py instead of the real CLI.

tests/fixtures/claude_turn.jsonl is hand-built after the documented `--output-format stream-json
--verbose --include-partial-messages` format: init, text deltas, assistant text and tool_use, tool
results (one a permission denial), and the final result with usage and modelUsage.
claude_turn_real.jsonl is an anonymized capture of the real CLI (2.1.283, one Read call), with the
thinking blocks and system/* events the hand-built one lacks.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import get_args

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from openbot.api.schemas import MODEL_OPTIONAL, Provider
from openbot.db.models import ActivityLog, Actor, BotProfile, InboxItem, Message, Run, RunEvent
from openbot.runtime import cli_agents
from openbot.runtime.cli_agents import ADAPTERS, adapter_for, base
from openbot.runtime.cli_agents.base import (
    EDIT,
    READ_ONLY,
    Turn,
    candidates,
    child_env,
    find_executable,
    login_status,
    render_messages,
    settings_error,
    since_last_reply,
)
from openbot.runtime.cli_agents.claude_code import result_usage, session_totals
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.runtime.providers import chat_model, effective_bot_profile, small_chat_model
from openbot.runtime.runner import TOOL_RESULT_CAP, Runner
from tests.conftest import build_test_services
from tests.factories import bot_actor

CLAUDE = ADAPTERS["claude-code"]
FIXTURES = Path(__file__).parent / "fixtures"
SESSION = "4f7c2a0e-9b1d-4c3e-8a5f-0d2e6b7c9a11"
OTHER_SESSION = "0e1d2c3b-4a59-4687-9a0b-c1d2e3f4a5b6"
TURN = (FIXTURES / "claude_turn.jsonl").read_text(encoding="utf-8").splitlines()
REAL_TURN = (FIXTURES / "claude_turn_real.jsonl").read_text(encoding="utf-8").splitlines()

# Paths this process opens, while a test asks for them. An audit hook cannot be removed again, so it
# stays installed and records only when a test sets the list.
_opened: list[str] | None = None


def _audit(event: str, args: tuple) -> None:
    if _opened is not None and event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        _opened.append(os.fsdecode(args[0]))


sys.addaudithook(_audit)


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) would terminate the process on Windows instead of probing it.
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259                                     # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def result_line(text: str, *, subtype: str = "success", is_error: bool = False, session: str = SESSION) -> str:
    return json.dumps({"type": "result", "subtype": subtype, "is_error": is_error, "num_turns": 1, "result": text,
                       "session_id": session, "usage": {"input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 7}})


def init_line(session: str = SESSION) -> str:
    return json.dumps({"type": "system", "subtype": "init", "session_id": session, "cwd": "/work", "tools": []})


def delta_line(text: str) -> str:
    return json.dumps({"type": "stream_event", "session_id": SESSION, "parent_tool_use_id": None,
                       "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}})


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A `claude` executable that runs tests/fake_claude.py with this interpreter; returns (dir, path)."""
    home = tmp_path / "fake_claude"
    home.mkdir()
    script_file = Path(__file__).parent / "fake_claude.py"
    if sys.platform == "win32":
        exe = home / "claude.cmd"
        exe.write_text(f'@"{sys.executable}" "{script_file}" %*\r\n', encoding="utf-8")
    else:
        exe = home / "claude"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script_file}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    monkeypatch.setenv("FAKE_CLAUDE_DIR", str(home))
    return home, exe


def script(home: Path, *steps: dict) -> None:
    (home / "script.json").write_text(json.dumps(list(steps)), encoding="utf-8")


def calls(home: Path) -> list[dict]:
    f = home / "calls.jsonl"
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


async def make(settings, *, model: str = "", model_settings: dict | None = None, content: str = "please build it"):
    services = await build_test_services(settings, {})
    services.actors = None            # drive the runner directly
    services.runner = Runner(services)
    async with services.session_factory() as s:
        eng = Actor(kind="bot", handle="eng", name="Eng", description="builds",
                    bot=BotProfile(provider="claude-code", model=model, model_settings=model_settings or {}))
        rev = bot_actor("rev", description="reviews")
        s.add_all([eng, rev])
        await s.commit()
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you, default_bot_handle="eng")
    run = await queue(services, t.id, eng.id, content)
    return services, eng, t, run


async def queue(services, thread_id: str, bot_id: str, content: str) -> Run:
    """Post a human message to the bot and claim its inbox item for a new run, as the actor system would."""
    async with services.session_factory() as s:
        you = await human_actor(s)
        res = await post_message(services, s, thread_id=thread_id, sender=you, content=f"@eng {content}")
        item = next(i for i in res.items if i.actor_id == bot_id)
        run = Run(actor_id=bot_id, thread_id=thread_id)
        s.add(run)
        await s.flush()
        item.run_id, item.status = run.id, "processing"
        await s.commit()
        return run


async def get(services, model, id_):
    async with services.session_factory() as s:
        return await s.get(model, id_)


async def events(services, run_id):
    async with services.session_factory() as s:
        return (await s.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq))).scalars().all()


async def thread_messages(services, thread_id):
    async with services.session_factory() as s:
        return (await s.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at))).scalars().all()


# --- the adapter registry ----------------------------------------------------------------------------

def test_every_adapter_is_a_provider_the_api_accepts():
    assert set(ADAPTERS) <= set(get_args(Provider)) and set(ADAPTERS) <= set(MODEL_OPTIONAL)
    assert adapter_for("claude-code") is CLAUDE and adapter_for("openai") is None and adapter_for(None) is None


# --- finding the CLI ---------------------------------------------------------------------------------

def test_candidates_search_path_then_install_dirs_on_windows():
    env = {"PATH": r"C:\tools;C:\bin", "PATHEXT": ".EXE;.CMD", "APPDATA": r"C:\Users\a\AppData\Roaming",
           "LOCALAPPDATA": r"C:\Users\a\AppData\Local"}
    c = candidates(CLAUDE, platform="win32", env=env, home=r"C:\Users\a")
    assert c[:4] == [r"C:\tools\claude.exe", r"C:\tools\claude.cmd", r"C:\bin\claude.exe", r"C:\bin\claude.cmd"]
    assert r"C:\Users\a\.local\bin\claude.exe" in c and r"C:\Users\a\AppData\Roaming\npm\claude.cmd" in c


def test_candidates_search_path_then_install_dirs_on_posix():
    c = candidates(CLAUDE, platform="linux", env={"PATH": "/usr/bin:/opt/x"}, home="/home/a")
    assert c[:2] == ["/usr/bin/claude", "/opt/x/claude"]
    assert c[2:] == ["/home/a/.local/bin/claude", "/home/a/.claude/local/claude", "/home/a/.npm-global/bin/claude",
                     "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]


def test_find_executable_uses_the_setting_or_the_first_runnable_candidate(settings, fake, tmp_path):
    _home, exe = fake
    assert find_executable(CLAUDE, settings, paths=[str(tmp_path / "missing"), str(exe)]) == str(exe)
    assert find_executable(CLAUDE, settings, paths=[str(tmp_path / "missing")]) is None
    settings.claude_code_path = str(exe)
    assert find_executable(CLAUDE, settings, paths=[]) == str(exe)
    # An explicit path is the only one tried: a typo must not silently pick another install.
    settings.claude_code_path = str(tmp_path / "nope")
    assert find_executable(CLAUDE, settings, paths=[str(exe)]) is None


# --- the environment and the credentials ---------------------------------------------------------------

def test_child_env_keeps_openbot_settings_and_keys_out():
    env = {"PATH": "/bin", "HOME": "/h", "OPENROUTER_API_KEY": "k", "OPENAI_API_KEY": "o", "SECRET_KEY": "s",
           "MCP_TOKEN_KEY": "m", "OPENBOT_API_KEY": "a", "TELEGRAM_BOT_TOKEN": "t", "DATABASE_URL": "d",
           "PUBLIC_URL": "u", "LANGSMITH_API_KEY": "l", "FOO": "bar"}
    assert child_env(env) == {"PATH": "/bin", "HOME": "/h", "FOO": "bar"}


SYSTEM_ENV = {"PATH": "p", "Path": "p", "HOME": "h", "USERPROFILE": "u", "APPDATA": "a", "LOCALAPPDATA": "l",
              "TEMP": "t", "TMP": "t", "SystemRoot": "s"}


def test_child_env_keeps_what_the_cli_needs_to_run(monkeypatch):
    assert child_env(SYSTEM_ENV) == SYSTEM_ENV
    # Even if OpenBot ever gets a setting with one of these names, the CLI still finds git, node and its config.
    monkeypatch.setattr(base, "_openbot_env_names",
                        lambda: {"PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "SYSTEMROOT", "SECRET_KEY"})
    assert child_env({**SYSTEM_ENV, "SECRET_KEY": "k"}) == SYSTEM_ENV


def test_a_provider_key_set_up_for_openbot_does_not_become_the_clis_login():
    # With it the CLI would bill that key instead of the subscription the user logged in with.
    assert child_env({"PATH": "/bin", "ANTHROPIC_API_KEY": "k"}) == {"PATH": "/bin"}


async def test_login_status_is_the_exit_code_of_the_clis_own_command(fake):
    home, exe = fake
    assert await login_status(CLAUDE, str(exe), child_env()) is True
    (home / "auth_exit.txt").write_text("1")
    assert await login_status(CLAUDE, str(exe), child_env()) is False
    assert await login_status(CLAUDE, str(home / "missing"), child_env()) is None


async def test_a_turn_opens_no_file_in_a_clis_config_directory(settings, fake, tmp_path, monkeypatch):
    """OpenBot starts the CLI and asks it for its login state; the credentials stay the CLI's business."""
    global _opened
    home, exe = fake
    user_home = tmp_path / "home"
    for name in (".claude/.credentials.json", ".codex/auth.json", ".gemini/oauth_creds.json"):
        (user_home / name).parent.mkdir(parents=True)
        (user_home / name).write_text("{}")
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    settings.claude_code_path = str(exe)
    script(home, {"lines": TURN})
    services, _eng, _t, run = await make(settings)
    _opened = []
    try:
        candidates(CLAUDE)
        await login_status(CLAUDE, str(exe), child_env())
        await services.runner.execute(run.id)
    finally:
        opened, _opened = _opened, None
    assert (await get(services, Run, run.id)).status == "completed"
    assert opened, "the audit hook saw nothing; the test would prove nothing"
    private = [p for p in opened if any(f"/{d}/" in p.replace("\\", "/") + "/" for d in (".claude", ".codex", ".gemini"))]
    assert private == []


def test_the_package_uses_no_keychain_or_credential_store():
    source = "".join(p.read_text(encoding="utf-8") for p in Path(cli_agents.__file__).parent.glob("*.py")).lower()
    for word in ("keyring", "find-generic-password", "secret-tool", "credread", ".credentials", "auth.json", "oauth_creds"):
        assert word not in source, word


# --- settings and the command line ---------------------------------------------------------------------

def test_settings_error():
    assert settings_error(CLAUDE, "", {}) is None
    assert settings_error(CLAUDE, "sonnet", {"permission": EDIT, "timeout_seconds": 60}) is None
    # There is no level that turns the CLI's permission checks off.
    for mode in ("bypassPermissions", "yolo", "danger-full-access", "auto"):
        assert "permission" in settings_error(CLAUDE, "", {"permission": mode})
    assert "model" in settings_error(CLAUDE, "--dangerously-skip-permissions", {})
    assert "timeout_seconds" in settings_error(CLAUDE, "", {"timeout_seconds": 0})


def test_read_only_offers_the_read_tools_and_nothing_that_writes_or_runs():
    # A permission mode alone would not do: the user's own allow rules still apply under dontAsk.
    turn = Turn(system_prompt_file="/tmp/p.md", session_id=None, model="", permission=READ_ONLY)
    assert CLAUDE.argv("claude", turn) == [
        "claude", "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--append-system-prompt-file", "/tmp/p.md", "--permission-mode", "dontAsk",
        "--restricted", "--strict-mcp-config", "--tools", "Read,Grep,Glob"]


def test_edit_adds_the_file_tools_and_still_no_tool_that_runs_commands():
    turn = Turn(system_prompt_file="/tmp/p.md", session_id=SESSION, model="opus", permission=EDIT)
    argv = CLAUDE.argv("claude", turn)
    assert argv[8:] == ["--permission-mode", "acceptEdits", "--restricted", "--strict-mcp-config",
                        "--tools", "Read,Grep,Glob,Edit,Write,NotebookEdit", "--model", "opus", "--resume", SESSION]


@pytest.mark.parametrize("permission", [READ_ONLY, EDIT])
def test_no_level_can_run_commands_reach_mcp_or_skip_permission_checks(permission):
    argv = CLAUDE.argv("claude", Turn(system_prompt_file="/tmp/p.md", session_id=None, model="", permission=permission))
    tools = argv[argv.index("--tools") + 1].split(",")
    assert not {"Bash", "PowerShell", "WebFetch", "WebSearch", "Task", "default"} & set(tools)
    assert "--restricted" in argv and "--strict-mcp-config" in argv
    assert not [a for a in argv if "bypass" in a.lower() or "dangerously" in a.lower()]


# --- the stream ----------------------------------------------------------------------------------------

def test_parser_turns_the_recorded_stream_into_run_actions():
    p = CLAUDE.parser()
    actions = [a for line in TURN for a in p.feed(json.loads(line))]
    assert [k for k, _ in actions] == ["session", "init", "delta", "delta", "text", "tool_call", "tool_result",
                                       "tool_call", "tool_result", "delta", "text"]
    assert p.session_id == SESSION
    assert actions[1][1] == {"model": "claude-sonnet-5", "permissionMode": "dontAsk", "apiKeySource": "none"}
    assert actions[5][1] == {"id": "toolu_01", "name": "Read", "args": {"file_path": "README.md"}}
    assert actions[6][1]["name"] == "Read" and actions[6][1]["status"] == "success" and "# Demo" in actions[6][1]["content"]
    assert actions[8][1] == {"tool_call_id": "toolu_02", "name": "Bash", "status": "error",
                             "content": "Permission to use Bash has been denied."}
    result = p.finish(exit_code=0, stderr="", resumed=False, baseline=None)
    assert result.text.endswith("@rev - please review the change.") and result.session_id == SESSION


def test_parser_keeps_subagent_text_out_of_the_reply():
    p = CLAUDE.parser()
    sub = {"type": "assistant", "parent_tool_use_id": "toolu_9", "session_id": SESSION,
           "message": {"content": [{"type": "text", "text": "subagent notes"}, {"type": "tool_use", "id": "t1", "name": "Grep", "input": {}}]}}
    assert [k for k, _ in p.feed(sub)] == ["session", "tool_call"]
    assert p.feed({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                                              "content": [{"type": "text", "text": "a"}, {"type": "image"}]}]}}) == [
        ("tool_result", {"tool_call_id": "t1", "name": "Grep", "status": "success", "content": "a\n[image]"})]


def test_parser_survives_a_real_captured_stream():
    # Thinking-only assistant events and the system/* events around the turn produce nothing.
    p = CLAUDE.parser()
    actions = [a for line in REAL_TURN for a in p.feed(json.loads(line))]
    kinds = [k for k, _ in actions]
    assert (kinds.count("init"), kinds.count("session"), kinds.count("tool_call"), kinds.count("tool_result"),
            kinds.count("text")) == (1, 1, 1, 1, 1)
    tool_call = actions[kinds.index("tool_call")][1]
    assert tool_call["name"] == "Read" and tool_call["args"]["file_path"].endswith("notes.md")
    assert actions[kinds.index("tool_result")][1]["status"] == "success"
    result = p.finish(exit_code=0, stderr="", resumed=False, baseline=None)
    assert result.text == actions[kinds.index("text")][1] and result.session_id == SESSION
    assert result.usage == {"prompt_tokens": 17 + 39993 + 38316, "completion_tokens": 378, "cache_read_tokens": 38316,
                            "cache_write_tokens": 39993, "reasoning_tokens": 238, "total_tokens": 17 + 39993 + 38316 + 378,
                            "model_calls": 2, "cost_usd": 0.0857246}


def test_usage_comes_from_model_usage_once_and_counts_cache_as_prompt():
    # The per-message usage on the assistant events repeats per content block; it is never added up.
    result = json.loads(TURN[-1])
    assert result_usage(result) == {"prompt_tokens": 18 + 300 + 1200 + 29500, "completion_tokens": 95 + 20,
                                    "cache_read_tokens": 29500, "cache_write_tokens": 1200, "reasoning_tokens": 0,
                                    "total_tokens": 18 + 300 + 1200 + 29500 + 115, "model_calls": 3, "cost_usd": 0.0123}
    del result["modelUsage"], result["total_cost_usd"]
    usage = result_usage(result)
    assert (usage["prompt_tokens"], usage["cost_usd"]) == (18 + 1200 + 29500, 0.0)


def real_result(usage: dict, model_usage: dict, cost: float) -> dict:
    return {"type": "result", "subtype": "success", "is_error": False, "num_turns": 1, "result": "ok", "session_id": SESSION,
            "total_cost_usd": cost, "usage": usage, "modelUsage": {"claude-haiku-4-5-20251001": {**model_usage, "costUSD": cost}}}


# The usage numbers of three real turns in one session (2.1.283): a fresh one and two resumed ones.
REAL_FRESH = real_result({"input_tokens": 10, "cache_creation_input_tokens": 35179, "cache_read_input_tokens": 0, "output_tokens": 74},
                         {"inputTokens": 10, "outputTokens": 74, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 35179,
                          "thinkingTokens": 68}, 0.070738)
REAL_SECOND = real_result({"input_tokens": 10, "cache_creation_input_tokens": 496, "cache_read_input_tokens": 35179, "output_tokens": 43},
                          {"inputTokens": 20, "outputTokens": 117, "cacheReadInputTokens": 35179, "cacheCreationInputTokens": 35675,
                           "thinkingTokens": 105}, 0.0754729)
REAL_THIRD = real_result({"input_tokens": 10, "cache_creation_input_tokens": 89, "cache_read_input_tokens": 35675, "output_tokens": 43},
                         {"inputTokens": 30, "outputTokens": 160, "cacheReadInputTokens": 70854, "cacheCreationInputTokens": 35764,
                          "thinkingTokens": 142}, 0.0794434)


def test_a_resumed_turn_counts_only_itself_although_the_cli_reports_the_whole_session():
    first = result_usage(REAL_FRESH)
    assert (first["prompt_tokens"], first["completion_tokens"], first["reasoning_tokens"]) == (10 + 35179, 74, 68)
    second = result_usage(REAL_SECOND, session_totals(REAL_FRESH))
    assert second == {"prompt_tokens": 10 + 496 + 35179, "completion_tokens": 43, "cache_read_tokens": 35179,
                      "cache_write_tokens": 496, "reasoning_tokens": 37, "total_tokens": 10 + 496 + 35179 + 43,
                      "model_calls": 1, "cost_usd": pytest.approx(0.0754729 - 0.070738)}
    third = result_usage(REAL_THIRD, session_totals(REAL_SECOND))
    assert (third["prompt_tokens"], third["cache_read_tokens"], third["completion_tokens"]) == (10 + 89 + 35675, 35675, 43)
    # Without the previous totals every earlier turn would be counted again.
    assert result_usage(REAL_THIRD)["prompt_tokens"] == 30 + 35764 + 70854


def test_a_cost_that_is_not_a_number_counts_as_zero():
    for cost in ("0.07", None, True):
        result = {**REAL_FRESH, "total_cost_usd": cost}
        assert result_usage(result)["cost_usd"] == 0.0
        assert result_usage({**result, "modelUsage": {}})["cost_usd"] == 0.0


def test_totals_that_are_not_per_session_are_taken_as_they_are():
    # A CLI that reports one invocation in modelUsage: subtracting the last turn would lose tokens.
    per_turn = real_result({"input_tokens": 10, "cache_creation_input_tokens": 500, "cache_read_input_tokens": 35000, "output_tokens": 40},
                           {"inputTokens": 10, "outputTokens": 40, "cacheReadInputTokens": 35000, "cacheCreationInputTokens": 500}, 0.004)
    usage = result_usage(per_turn, session_totals(REAL_FRESH))
    assert (usage["prompt_tokens"], usage["completion_tokens"], usage["cost_usd"]) == (10 + 500 + 35000, 40, 0.004)


def test_render_and_since_last_reply():
    history = [HumanMessage(content="[You]: hi"), AIMessage(content="hello"), HumanMessage(content="[You] (new): build it")]
    assert render_messages(history, "Eng") == "[You]: hi\n\n[Eng (you)]: hello\n\n[You] (new): build it"
    assert since_last_reply(history) == history[2:]
    assert since_last_reply(history[:1]) == history[:1]


# --- side tasks ----------------------------------------------------------------------------------------

def test_cli_bots_are_never_rerouted_and_side_tasks_use_the_default_provider(settings):
    profile = BotProfile(provider="claude-code", model="opus", model_settings={"permission": EDIT})
    assert effective_bot_profile(profile, settings) == ("claude-code", "opus")
    # A CLI is not a chat model: without a configured provider the title and memory calls fail like an auto bot's.
    for factory in (chat_model, small_chat_model):
        with pytest.raises(ValueError, match="no provider is configured"):
            factory(profile, settings)
    settings.openrouter_api_key = "k"
    assert effective_bot_profile(profile, settings) == ("claude-code", "opus")
    assert chat_model(profile, settings).model_name == "openai/gpt-4o-mini"
    assert small_chat_model(profile, settings) is not None


# --- runs ----------------------------------------------------------------------------------------------

async def test_run_spawns_the_cli_streams_events_and_hands_off(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": TURN})
    services, eng, t, run = await make(settings)
    await services.runner.execute(run.id)

    run = await get(services, Run, run.id)
    assert run.status == "completed", run.error
    assert (run.prompt_tokens, run.completion_tokens, run.cache_read_tokens, run.cache_write_tokens, run.model_calls) == (
        31018, 115, 29500, 1200, 3)
    assert run.cost_usd == pytest.approx(0.0123)
    [call] = calls(home)
    assert Path(call["cwd"]).resolve() == settings.workspace_root.resolve()
    assert call["argv"][:5] == ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
    assert call["argv"][call["argv"].index("--permission-mode") + 1] == "dontAsk" and "--resume" not in call["argv"]
    assert call["argv"][call["argv"].index("--tools") + 1] == "Read,Grep,Glob" and "--restricted" in call["argv"]
    assert "[You] (new): @eng please build it" in call["stdin"]
    assert "You are Eng (@eng)" in call["system_prompt"] and "@rev (Rev)" in call["system_prompt"]
    assert "inside the Claude Code CLI" in call["system_prompt"]
    assert "FAKE_CLAUDE_DIR" in call["env"] and "SECRET_KEY" not in call["env"]
    assert [e.type for e in await events(services, run.id)] == ["cli_session", "text", "tool_call", "tool_result",
                                                                "tool_call", "tool_result", "text", "message", "cli_session"]
    reply = (await thread_messages(services, t.id))[-1]
    assert reply.sender_actor_id == eng.id and reply.run_id == run.id and reply.content.endswith("@rev - please review the change.")
    async with services.session_factory() as s:
        rev = (await s.execute(select(Actor).where(Actor.handle == "rev"))).scalar_one()
        woken = (await s.execute(select(InboxItem.actor_id).where(InboxItem.message_id == reply.id))).scalars().all()
    assert rev.id in woken and eng.id not in woken
    session, after = [e.payload for e in await events(services, run.id) if e.type == "cli_session"]
    assert session == {"agent": "claude-code", "session_id": SESSION, "cwd": call["cwd"]}
    assert after == {**session, "totals": session_totals(json.loads(TURN[-1]))}


async def test_the_edit_level_maps_to_accept_edits(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": [init_line(), result_line("ok")]})
    services, _eng, _t, run = await make(settings, model="opus", model_settings={"permission": EDIT})
    await services.runner.execute(run.id)
    argv = calls(home)[0]["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits" and argv[argv.index("--model") + 1] == "opus"


async def test_openbots_anthropic_key_stays_out_and_the_log_names_where_the_cli_got_its_login(settings, fake, monkeypatch):
    home, exe = fake
    settings.claude_code_path = str(exe)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    script(home, {"lines": [json.dumps({**json.loads(init_line()), "apiKeySource": "none"}), result_line("ok")]})
    services, _eng, _t, run = await make(settings)
    await services.runner.execute(run.id)
    assert "ANTHROPIC_API_KEY" not in calls(home)[0]["env"]
    async with services.session_factory() as s:
        row = (await s.execute(select(ActivityLog).where(ActivityLog.run_id == run.id,
                                                         ActivityLog.event == "run.cli_session"))).scalar_one()
    assert row.detail["apiKeySource"] == "none" and row.detail["agent"] == "claude-code"


async def test_lines_far_past_the_default_stream_limit_are_read_whole(settings, fake):
    # asyncio's default is 64 KiB per line; one file read in a tool_result is easily more.
    home, exe = fake
    settings.claude_code_path = str(exe)
    big = "Gr\u00f6\u00dfe: " + "x" * 300_000
    lines = [init_line(),
             json.dumps({"type": "assistant", "session_id": SESSION, "parent_tool_use_id": None,
                         "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "big.txt"}}]}}),
             json.dumps({"type": "user", "session_id": SESSION, "parent_tool_use_id": None,
                         "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": big}]}}, ensure_ascii=False),
             result_line("Die Datei ist gro\u00df.")]
    script(home, {"lines": lines})
    services, _eng, t, run = await make(settings)
    await services.runner.execute(run.id)
    assert (await get(services, Run, run.id)).status == "completed"
    [result] = [e.payload for e in await events(services, run.id) if e.type == "tool_result"]
    assert result["content"] == big[:TOOL_RESULT_CAP]
    assert (await thread_messages(services, t.id))[-1].content == "Die Datei ist gro\u00df."


async def test_follow_up_resumes_the_session_with_only_new_messages(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": TURN}, {"lines": [init_line(), result_line("Tests added.")]})
    services, eng, t, run = await make(settings)
    await services.runner.execute(run.id)
    second = await queue(services, t.id, eng.id, "now add tests")
    await services.runner.execute(second.id)

    assert (await get(services, Run, second.id)).status == "completed"
    _first_call, second_call = calls(home)
    assert second_call["argv"][second_call["argv"].index("--resume") + 1] == SESSION
    assert "now add tests" in second_call["stdin"] and "please build it" not in second_call["stdin"]
    # The system prompt is sent again each turn: the roster and memories may have changed since.
    assert "You are Eng (@eng)" in second_call["system_prompt"]
    assert (await thread_messages(services, t.id))[-1].content == "Tests added."
    # The version is checked once per install, not on every turn.
    assert (home / "versions.txt").read_text() == "x"


async def test_a_resumed_run_is_charged_only_its_own_turn(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": [init_line(), json.dumps(REAL_FRESH)]}, {"lines": [init_line(), json.dumps(REAL_SECOND)]})
    services, eng, t, run = await make(settings)
    await services.runner.execute(run.id)
    second = await queue(services, t.id, eng.id, "and again")
    await services.runner.execute(second.id)
    first, second = await get(services, Run, run.id), await get(services, Run, second.id)
    assert (first.prompt_tokens, first.completion_tokens, first.cost_usd) == (10 + 35179, 74, pytest.approx(0.070738))
    assert (second.prompt_tokens, second.completion_tokens, second.cache_read_tokens) == (10 + 496 + 35179, 43, 35179)
    assert second.cost_usd == pytest.approx(0.0754729 - 0.070738)


async def test_a_session_the_cli_no_longer_knows_starts_over_with_the_thread(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": TURN},
           {"stderr": f"No conversation found with session ID: {SESSION}\n", "exit": 1},
           {"lines": [init_line(OTHER_SESSION), result_line("Fresh start.", session=OTHER_SESSION)]})
    services, eng, t, run = await make(settings)
    await services.runner.execute(run.id)
    second = await queue(services, t.id, eng.id, "again")
    await services.runner.execute(second.id)

    assert (await get(services, Run, second.id)).status == "completed"
    _first, gone, fresh = calls(home)
    assert "--resume" in gone["argv"] and "--resume" not in fresh["argv"]
    assert "please build it" in fresh["stdin"] and "again" in fresh["stdin"]
    stored = [e.payload for e in await events(services, second.id) if e.type == "cli_session"]
    assert [p["session_id"] for p in stored] == [OTHER_SESSION]


@pytest.mark.parametrize("stored", [
    {"agent": "claude-code", "session_id": SESSION, "cwd": "/elsewhere"},   # the CLIs key transcripts by directory
    {"agent": "codex", "session_id": SESSION},                              # another CLI's session; cwd filled in below
])
async def test_a_session_from_elsewhere_is_not_resumed(settings, fake, stored):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": [init_line(), result_line("ok")]})
    services, _eng, _t, run = await make(settings)
    async with services.session_factory() as s:
        s.add(RunEvent(run_id=run.id, seq=99, type="cli_session", payload={"cwd": str(settings.workspace_root), **stored}))
        await s.commit()
    await services.runner.execute(run.id)
    assert "--resume" not in calls(home)[0]["argv"]


async def test_a_cli_too_old_for_restricted_mode_fails_before_it_runs(settings, fake, monkeypatch):
    # Without --restricted neither permission level would hold.
    home, exe = fake
    settings.claude_code_path = str(exe)
    monkeypatch.setenv("FAKE_CLAUDE_VERSION", "2.1.100 (Claude Code)")
    script(home, {"lines": [init_line(), result_line("should not run")]})
    services, _eng, _t, run = await make(settings)
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "failed"
    assert run.error == "error: Claude Code 2.1.100 is too old; OpenBot needs 2.1.248 or later. Update it with `claude update`."
    assert calls(home) == []


async def test_an_unreadable_version_fails_the_run(settings, fake, monkeypatch):
    home, exe = fake
    settings.claude_code_path = str(exe)
    monkeypatch.setenv("FAKE_CLAUDE_VERSION", "unknown")
    script(home, {"lines": [init_line(), result_line("should not run")]})
    services, _eng, _t, run = await make(settings)
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "failed" and run.error.startswith("error: could not read the Claude Code version") and calls(home) == []


async def test_a_missing_cli_fails_the_run_with_a_clear_error(settings, tmp_path):
    settings.claude_code_path = str(tmp_path / "no-claude")
    services, _eng, t, run = await make(settings)
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "failed" and run.error.startswith("error: Claude Code CLI (claude) not found")
    assert "CLAUDE_CODE_PATH" in run.error
    assert (await thread_messages(services, t.id))[-1].content.startswith("@eng failed: error: Claude Code CLI")


async def test_an_error_result_fails_the_run_and_keeps_its_usage(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": [init_line(), result_line("Credit balance is too low", subtype="error_during_execution", is_error=True)],
                  "exit": 1})
    services, _eng, _t, run = await make(settings)
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "failed" and run.error == "error: claude run failed (error_during_execution): Credit balance is too low"
    assert (run.prompt_tokens, run.completion_tokens, run.model_calls) == (105, 7, 1)


async def test_a_crash_without_result_reports_stderr(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"stderr": "error: unknown option '--include-partial-messages'\n", "exit": 2})
    services, _eng, _t, run = await make(settings)
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "failed" and "exited with code 2" in run.error and "unknown option" in run.error


async def test_a_failed_run_of_a_cli_that_is_not_logged_in_says_so(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    (home / "auth_exit.txt").write_text("1")
    script(home, {"stderr": "Invalid API key\n", "exit": 1})
    services, _eng, t, run = await make(settings)
    await services.runner.execute(run.id)
    run = await get(services, Run, run.id)
    assert run.status == "failed"
    assert run.error == "error: Claude Code is not logged in. Run `claude auth login` in a terminal."
    assert "claude auth login" in (await thread_messages(services, t.id))[-1].content


async def wait_for_pids(home: Path) -> tuple[int, int]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        f = home / "pids.txt"
        if f.exists() and len(f.read_text().split()) == 2:
            a, b = f.read_text().split()
            return int(a), int(b)
        await asyncio.sleep(0.05)
    raise AssertionError("the fake claude never started its child")


async def wait_dead(*pids: int) -> bool:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not any(alive(p) for p in pids):
            return True
        await asyncio.sleep(0.05)
    return False


async def test_cancelling_a_run_stops_the_cli_and_its_children_and_keeps_what_it_wrote(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": [init_line(), delta_line("Half an "), delta_line("answer for @rev")], "hang": True})
    services, eng, t, run = await make(settings)
    async with services.bus.subscribe(t.id) as q:
        task = asyncio.create_task(services.runner.execute(run.id))
        streamed = ""
        while streamed != "Half an answer for @rev":      # cancel only once the runner has seen the stream
            ev = await asyncio.wait_for(q.get(), 20)
            if ev["event"] == "run.event" and ev["data"].get("type") == "text_delta":
                streamed += ev["data"]["payload"]["delta"]
    parent, child = await wait_for_pids(home)
    assert alive(parent) and alive(child)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await wait_dead(parent, child)
    assert (await get(services, Run, run.id)).status == "cancelled"
    kept, notice = (await thread_messages(services, t.id))[-2:]
    assert (kept.sender_actor_id, kept.content, kept.meta) == (eng.id, "Half an answer for @rev", {"interrupted": True})
    assert notice.content == "@eng run was cancelled."
    # The half-written @rev wakes nobody.
    async with services.session_factory() as s:
        rev = (await s.execute(select(Actor).where(Actor.handle == "rev"))).scalar_one()
        assert rev.id not in (await s.execute(select(InboxItem.actor_id).where(InboxItem.message_id == kept.id))).scalars().all()


async def test_a_process_the_cli_leaves_behind_neither_holds_up_the_run_nor_survives_it(settings, fake):
    # It inherits the CLI's stdout and stderr, so both pipes stay open after the CLI has exited.
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": [init_line(), result_line("Started the dev server.")], "leave_child": True})
    services, _eng, t, run = await make(settings, model_settings={"timeout_seconds": 60})
    started = time.monotonic()
    await services.runner.execute(run.id)
    assert time.monotonic() - started < 30
    run = await get(services, Run, run.id)
    assert run.status == "completed", run.error
    assert (await thread_messages(services, t.id))[-1].content == "Started the dev server."
    _parent, child = await wait_for_pids(home)
    assert await wait_dead(child)


async def test_a_run_past_its_timeout_is_stopped(settings, fake):
    home, exe = fake
    settings.claude_code_path = str(exe)
    script(home, {"lines": [init_line()], "hang": True})
    services, _eng, _t, run = await make(settings, model_settings={"timeout_seconds": 3})
    await services.runner.execute(run.id)
    parent, child = await wait_for_pids(home)
    assert await wait_dead(parent, child)
    run = await get(services, Run, run.id)
    assert run.status == "failed" and run.error == "error: claude did not finish within 3s and was stopped"


@pytest.mark.parametrize(("api_key", "expected"), [("k", True), (None, False)])
async def test_memory_reflection_follows_a_cli_run_only_with_a_chat_provider(settings, fake, api_key, expected):
    home, exe = fake
    settings.claude_code_path = str(exe)
    settings.openrouter_api_key = api_key
    script(home, {"lines": [init_line(), result_line("done and dusted")]})
    services, eng, _t, run = await make(settings)
    scheduled = []
    services.reflector.schedule = lambda bot, messages, thread_id: scheduled.append((bot.id, messages))
    await services.runner.execute(run.id)
    assert bool(scheduled) is expected
    if expected:
        bot_id, messages = scheduled[0]
        assert bot_id == eng.id and messages[-1].content == "done and dusted"


# --- API -----------------------------------------------------------------------------------------------

async def test_api_accepts_cli_bots_without_a_model_and_checks_their_settings(client):
    r = await client.post("/api/v1/bots", json={"handle": "coder", "name": "Coder", "provider": "claude-code"})
    assert r.status_code == 201 and r.json()["provider"] == "claude-code" and r.json()["model"] == ""
    url = f"/api/v1/bots/{r.json()['id']}"
    bad = await client.patch(url, json={"model_settings": {"permission": "bypassPermissions"}})
    assert bad.status_code == 422 and "permission" in bad.text
    assert (await client.patch(url, json={"model_settings": {"permission": "edit"}})).status_code == 200
    bad = await client.post("/api/v1/bots", json={"handle": "coder2", "name": "Coder", "provider": "claude-code",
                                                  "model": "--resume"})
    assert bad.status_code == 422 and "model" in bad.text


def test_settings_default_timeout(settings):
    assert settings.cli_agent_timeout == 1800 and settings.claude_code_path is None
