"""The runner's side of a CLI turn: session lookup, the CLI's events as run events, the reply."""
from __future__ import annotations

import logging
import time

from langchain_core.messages import AIMessage
from sqlalchemy import select

from openbot.db.models import Run, RunEvent
from openbot.runtime import activity
from openbot.runtime.cli_agents.base import (
    CliAdapter,
    CliAgentError,
    child_env,
    find_executable,
    login_status,
    render_messages,
    run_turn,
    since_last_reply,
)
from openbot.runtime.delivery import post_message
from openbot.runtime.providers import default_provider

log = logging.getLogger(__name__)


def prompt_text(system_prompt) -> str:
    content = getattr(system_prompt, "content", system_prompt)
    if isinstance(content, str):
        return content
    return "\n\n".join(p["text"] for p in content if isinstance(p, dict) and p.get("type") == "text")


def cli_note(adapter: CliAdapter) -> str:
    return (f"\n\n# How this turn runs\nYou are running inside the {adapter.label} CLI, in the working directory above. "
            "Use its own tools for files and commands. OpenBot's own tools described in this prompt are not "
            "available in this turn. Your final message is posted to the thread as your reply, so hand off by "
            "@mentioning a bot in it.")


async def _last_session(runner, bot_id: str, thread_id: str) -> dict | None:
    """The CLI session this bot last used in this thread. Kept as a `cli_session` run event, so it needs
    no table and goes away with the thread."""
    async with runner.s.session_factory() as session:
        return (await session.execute(
            select(RunEvent.payload).join(Run, Run.id == RunEvent.run_id)
            .where(Run.actor_id == bot_id, Run.thread_id == thread_id, RunEvent.type == "cli_session")
            .order_by(RunEvent.created_at.desc(), RunEvent.seq.desc()).limit(1))).scalar()


async def execute_cli_turn(runner, adapter: CliAdapter, bot, thread, run, seq: int, system_prompt, history: list,
                           workspace_root, hop: int, progress, started: float) -> None:
    """Like the rest of Runner.execute, for a bot whose provider is a CLI. `progress` is filled as the
    stream arrives, so a cancelled run keeps what the CLI had written."""
    from openbot.runtime.runner import TOOL_RESULT_CAP

    s = runner.s
    executable = find_executable(adapter, s.settings)
    if executable is None:
        raise CliAgentError(adapter.not_found)
    workspace_root.mkdir(parents=True, exist_ok=True)
    cwd = str(workspace_root)
    previous = await _last_session(runner, bot.id, thread.id)
    # A session only resumes where it was made: the CLIs key their transcripts by working directory.
    resume = None
    if previous and previous.get("agent") == adapter.provider and previous.get("session_id") and previous.get("cwd") == cwd:
        resume = (previous["session_id"], render_messages(since_last_reply(history) or history, bot.name),
                  previous.get("totals"))
    env = child_env()

    async def on_event(kind: str, payload) -> None:
        nonlocal seq, session_id
        if kind == "delta":
            progress.streaming += payload
            await s.bus.publish("run.event", run.thread_id, {"run_id": run.id, "type": "text_delta", "payload": {"delta": payload}})
        elif kind == "text":
            progress.streaming, progress.reply = "", payload
            seq = await runner._record(run, seq, "text", {"content": payload})
        elif kind == "tool_call":
            progress.tool_calls += 1
            log.info("run %s tool_call %s(%s)", run.id, payload["name"], activity.preview(payload["args"], 500))
            seq = await runner._record(run, seq, "tool_call", payload)
            await activity.record(s, "run.tool_call", level="debug", thread_id=run.thread_id, actor_id=run.actor_id,
                                  run_id=run.id, summary=f"{payload['name']}({activity.preview(payload['args'], 200)})",
                                  name=payload["name"], args=activity.preview(payload["args"]))
        elif kind == "tool_result":
            content = payload["content"]
            log.info("run %s tool_result %s status=%s len=%d", run.id, payload["name"], payload["status"], len(content))
            seq = await runner._record(run, seq, "tool_result", {**payload, "content": content[:TOOL_RESULT_CAP]})
            await activity.record(s, "run.tool_result", level="warning" if payload["status"] == "error" else "debug",
                                  thread_id=run.thread_id, actor_id=run.actor_id, run_id=run.id,
                                  summary=f"{payload['name']} -> {payload['status']} ({len(content)} chars)",
                                  name=payload["name"], status=payload["status"], chars=len(content),
                                  content=activity.preview(content))
        elif kind == "session":
            session_id = payload
            seq = await runner._record(run, seq, "cli_session", {"agent": adapter.provider, "session_id": payload,
                                                                 "cwd": cwd})
        elif kind == "init":
            await activity.record(s, "run.cli_session", thread_id=run.thread_id, actor_id=run.actor_id, run_id=run.id,
                                  summary=f"{adapter.binary} started", agent=adapter.provider, cwd=cwd,
                                  resumed=resume is not None, **payload)

    session_id = None

    async def session_totals(totals: dict | None, seq: int) -> int:
        """A CLI that counts usage per session needs its last count on the next turn; the newest
        `cli_session` event of the thread carries it."""
        if totals is None or session_id is None:
            return seq
        return await runner._record(run, seq, "cli_session", {"agent": adapter.provider, "session_id": session_id,
                                                             "cwd": cwd, "totals": totals})

    ms = bot.bot.model_settings or {}
    try:
        result = await run_turn(adapter, executable, cwd=cwd, env=env,
                                system_prompt=prompt_text(system_prompt) + cli_note(adapter),
                                full_prompt=render_messages(history, bot.name), resume=resume, model=bot.bot.model,
                                model_settings=ms, timeout=ms.get("timeout_seconds") or s.settings.cli_agent_timeout,
                                on_event=on_event)
    except CliAgentError as e:
        if e.usage:
            await runner._set_status(run.id, "running", usage=e.usage)
            seq = await session_totals(e.totals, seq)
        # The CLI's own message for a missing login is rarely actionable; ask it directly.
        if await login_status(adapter, executable, env) is False:
            raise CliAgentError(f"error: {adapter.label} is not logged in. {adapter.login_hint}") from e
        raise
    if result.text.strip():
        async with s.session_factory() as session:
            res = await post_message(s, session, thread_id=thread.id, sender=bot, content=result.text, hop=hop, run_id=run.id)
        seq = await runner._record(run, seq, "message", {"message_id": res.message.id})
    usage = result.usage
    seq = await session_totals(result.totals, seq)
    await runner._set_status(run.id, "completed", usage=usage)
    log.info("run %s completed in %.1fs via %s: reply=%d chars model_calls=%d prompt_tokens=%d cache_read_tokens=%d "
             "completion_tokens=%d session=%s resumed=%s", run.id, time.monotonic() - started, adapter.binary,
             len(result.text), usage["model_calls"], usage["prompt_tokens"], usage["cache_read_tokens"],
             usage["completion_tokens"], result.session_id, resume is not None)
    # Reflection needs a chat model, and a CLI bot has none of its own (see providers.side_task_profile).
    # Without a configured provider it would only fail and log, so it is not scheduled. The transcript is
    # the thread as the bot saw it plus its reply; the CLI's tool calls are not part of it.
    if (bot.bot.memory_enabled and s.reflector is not None and result.text.strip()
            and default_provider(s.settings) is not None):
        try:
            s.reflector.schedule(bot, [*history, AIMessage(content=result.text)], thread_id=thread.id)
        except Exception:
            log.exception("could not schedule memory reflection for run %s", run.id)
