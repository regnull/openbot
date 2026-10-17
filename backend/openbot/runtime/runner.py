from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    SummarizationMiddleware,
)
from langchain.agents.middleware.summarization import DEFAULT_SUMMARY_PROMPT
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tracers.context import collect_runs
from langgraph.types import Command
from sqlalchemy import func, select

from openbot.api.schemas import RunEventOut, RunOut, to_json
from openbot.db.models import (
    Actor,
    InboxItem,
    Message,
    Run,
    RunEvent,
    Thread,
    ThreadParticipant,
    utcnow,
)
from openbot.runtime import activity, memory
from openbot.runtime.caching import caching_middleware
from openbot.runtime.cli_agents import CliAgentError, adapter_for
from openbot.runtime.cli_agents.run import execute_cli_turn
from openbot.runtime.delivery import DEFAULT_BOT_HANDLE, deliver_question, post_message
from openbot.runtime.prompt import build_history, build_system_prompt_parts
from openbot.runtime.providers import builtin_tools, effective_bot_profile
from openbot.runtime.retry import ModelRetryMiddleware
from openbot.runtime.tool_failures import ToolFailureMiddleware
from openbot.tools.builtin.core import CORE_TOOLS
from openbot.tools.builtin.scheduling import SCHEDULING_TOOLS
from openbot.tools.builtin.todo import load_todos, todo_list_section
from openbot.tools.builtin.workspace import thread_workspace_root
from openbot.tools.context import RunContext

log = logging.getLogger(__name__)
TOOL_RESULT_CAP = 4000
LOG_PREVIEW_CAP = 500
CLEARED_ARG_CAP = 120  # chars of each argument kept on a cleared tool call
CLEARED_PREVIEW_CAP = 160  # chars of the result's opening kept in its digest
USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_tokens",
    "model_calls",
)


def empty_usage() -> dict[str, int | float]:
    return {**dict.fromkeys(USAGE_KEYS, 0), "cost_usd": 0.0}


def add_usage(
    total: dict[str, int | float], message: AIMessage, price: dict[str, Any] | None = None
) -> dict[str, int | float] | None:
    """Fold one model reply's usage_metadata into `total`, including estimated USD cost.

    Pricing tiers follow OpenCode's session cost calculation: the tier selected by the prompt size
    prices the complete input, rather than only the tokens above the tier boundary.
    """
    um = getattr(message, "usage_metadata", None)
    if not um:
        return None
    input_details = um.get("input_token_details") or {}
    output_details = um.get("output_token_details") or {}
    inc: dict[str, int | float] = {
        "prompt_tokens": int(um.get("input_tokens") or 0),
        "completion_tokens": int(um.get("output_tokens") or 0),
        "cache_read_tokens": int(input_details.get("cache_read") or 0),
        "cache_write_tokens": int(input_details.get("cache_write") or 0),
        "reasoning_tokens": int(output_details.get("reasoning") or um.get("reasoning_tokens") or 0),
        "total_tokens": int(um.get("total_tokens") or 0),
        "model_calls": 1,
    }
    if price:
        rates = price
        tiers = [
            t
            for t in price.get("tiers", [])
            if isinstance(t, dict) and isinstance(t.get("tier"), dict)
        ]
        if tiers:
            applicable = [t for t in tiers if int(t["tier"].get("size", 0)) <= inc["prompt_tokens"]]
            if applicable:
                rates = {**price, **applicable[-1]}
        uncached_input = max(
            0, inc["prompt_tokens"] - inc["cache_read_tokens"] - inc["cache_write_tokens"]
        )
        inc["cost_usd"] = (
            uncached_input * float(rates.get("input") or 0)
            + inc["completion_tokens"] * float(rates.get("output") or 0)
            + inc["cache_read_tokens"] * float(rates.get("cache_read") or 0)
            + inc["cache_write_tokens"] * float(rates.get("cache_write") or 0)
        ) / 1_000_000
    else:
        inc["cost_usd"] = 0.0
    for k, v in inc.items():
        total[k] += v
    return inc


def _preview(value: Any, cap: int = LOG_PREVIEW_CAP) -> str:
    """Single-line, size-capped rendering of tool args/results for the diagnostic log."""
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    text = text.replace("\n", "\\n")
    return text if len(text) <= cap else text[:cap] + f"... [{len(text) - cap} more chars]"


def normalize_interrupt(value: Any) -> dict:
    if isinstance(value, dict):
        if value.get("kind") == "question":
            return {"kind": "question", "question": str(value.get("question", ""))}
        if "action_requests" in value:
            return {
                "kind": "approval",
                "actions": [
                    {"name": a.get("name"), "args": a.get("args", {})}
                    for a in value["action_requests"]
                ],
            }
    return {"kind": "question", "question": str(value)}


def _text(m) -> str:
    # langchain-core >= 1.6 exposes .text as a str-like accessor; older versions as a method.
    t = getattr(m, "text", None)
    if isinstance(t, str):
        return str(t)
    return t() if callable(t) else ""


# Text this long that a turn sends alongside tool calls is a report, not narration ("Let me check X").
REPORT_MIN_CHARS = 500


def compose_reply(reports: list[str], final_text: str) -> str:
    """The thread message a run posts. Only the last turn's text used to be posted, so an engineer that
    wrote its full report next to one more tool call, then closed with "report above is complete",
    handed the other bots a pointer to a report nobody could see. Reports come first, in order. Only
    the final text addresses anyone: the poster parses mentions from it alone (see `mention_text`)."""
    parts = [r for r in reports if r != final_text.strip()]
    if not parts:
        return final_text
    return "\n\n".join([*parts, final_text.strip()]) if final_text.strip() else "\n\n".join(parts)


@dataclass(slots=True)
class RunProgress:
    """What a run has produced so far, kept outside `_stream` so a cancelled run can still post it."""

    reply: str = ""  # text of the last finished model turn
    streaming: str = ""  # text of the turn still streaming
    tool_calls: int = 0
    reports: list[str] = field(default_factory=list)  # long text sent alongside tool calls; see compose_reply


def _message_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = [p if isinstance(p, str) else p.get("text", "") for p in content or [] if isinstance(p, (str, dict))]
    return "\n".join(p for p in parts if p)


def _clip(value: str, cap: int) -> str:
    return value if len(value) <= cap else f"{value[:cap]}… [{len(value)} chars]"


def cleared_digest(tool_message: ToolMessage, content: str) -> str:
    """The one line a cleared tool result is replaced with: did it work, how big was it, how did it start."""
    failed = tool_message.status == "error" or content.lstrip().lower().startswith("error")
    opening = _clip(" ".join(content.split()), CLEARED_PREVIEW_CAP)
    return (
        f"[cleared to save context: {'error' if failed else 'ok'}, {len(content)} chars, began: {opening!r}. "
        "This call already ran; repeat it only if you need its exact output again]"
    )


def _shorten_tool_call_args(message: AIMessage, tool_call_id: str) -> AIMessage:
    """`message` with the args of call `tool_call_id` clipped to `CLEARED_ARG_CAP` chars each."""

    def shorten(value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        return value if len(text) <= CLEARED_ARG_CAP else _clip(text, CLEARED_ARG_CAP)

    calls = [
        {**c, "args": {k: shorten(v) for k, v in (c.get("args") or {}).items()}}
        if c.get("id") == tool_call_id
        else c
        for c in message.tool_calls
    ]
    metadata = dict(message.response_metadata or {})
    entry = dict(metadata.get("context_editing", {}))
    entry["cleared_tool_inputs"] = sorted({*entry.get("cleared_tool_inputs", []), tool_call_id})
    metadata["context_editing"] = entry
    return message.model_copy(update={"tool_calls": calls, "response_metadata": metadata})


@dataclass(slots=True)
class ClearOlderTurnsEdit(ClearToolUsesEdit):
    """`ClearToolUsesEdit` that works in model turns, not in single results.

    The parent keeps the `keep` most recent tool results. A coding bot reads ten files in one turn, so
    with `keep=3` seven of the results it asked for one call ago came back as placeholders, it asked
    for them again, and the run cycled without ever writing a file. Here everything the last
    `keep_turns` model turns asked for is protected, however many results that is; older turns are
    cleared oldest first until `clear_at_least` tokens are reclaimed.

    A cleared call is shortened, not erased. The parent sets its args to `{}` and its result to one
    fixed placeholder, so the model could no longer tell which URL it had fetched or that the fetch had
    failed: an engineer run hunted the same missing file three times in 30 minutes. Here the call keeps
    each argument clipped to `CLEARED_ARG_CAP` chars and the result becomes a one-line digest (status,
    size, opening words), a few dozen tokens instead of thousands."""

    keep_turns: int = 2

    def apply(self, messages, *, count_tokens) -> None:
        tokens = count_tokens(messages)
        if tokens <= self.trigger:
            return
        protected: set[str] = set()
        turns = 0
        for m in reversed(messages):
            if isinstance(m, AIMessage) and m.tool_calls:
                protected.update(tc["id"] for tc in m.tool_calls)
                turns += 1
                if turns >= self.keep_turns:
                    break
        candidates = [
            (i, m)
            for i, m in enumerate(messages)
            if isinstance(m, ToolMessage) and m.tool_call_id not in protected
        ]
        if self.keep:
            candidates = candidates[: -self.keep] if self.keep < len(candidates) else []
        excluded = set(self.exclude_tools)
        for idx, tool_message in candidates:
            if tool_message.response_metadata.get("context_editing", {}).get("cleared"):
                continue
            ai_message = next(
                (m for m in reversed(messages[:idx]) if isinstance(m, AIMessage)), None
            )
            if ai_message is None:
                continue
            tool_call = next(
                (c for c in ai_message.tool_calls if c.get("id") == tool_message.tool_call_id), None
            )
            if tool_call is None or (tool_message.name or tool_call["name"]) in excluded:
                continue
            content = _message_text(tool_message.content)
            digest = cleared_digest(tool_message, content)
            messages[idx] = tool_message.model_copy(
                update={
                    "artifact": None,
                    "content": digest if len(digest) < len(content) else content,
                    "response_metadata": {
                        **tool_message.response_metadata,
                        "context_editing": {"cleared": True, "strategy": "clear_tool_uses"},
                    },
                }
            )
            if self.clear_tool_inputs:
                ai_index = messages.index(ai_message)
                messages[ai_index] = _shorten_tool_call_args(ai_message, tool_message.tool_call_id)
            if self.clear_at_least > 0 and tokens - count_tokens(messages) >= self.clear_at_least:
                break


# LangChain's summary prompt, plus two sections a coding run needs to stop rediscovering things: what
# it has already established, and what it already tried that did not work.
RUN_SUMMARY_PROMPT = DEFAULT_SUMMARY_PROMPT.replace(
    "\n## ARTIFACTS\n",
    """
## FACTS ESTABLISHED

Concrete findings later steps rely on: where things live (file paths, line ranges, function names, URLs
that worked), how the code behaves, and answers to questions already settled. Record moved or renamed
things as "X is not at A; it is at B".

## DEAD ENDS

Every attempt that failed or found nothing: missing files and URLs (with the exact path or URL), commands
that errored, searches with no hits, approaches rejected. Later steps must not repeat these.

## ARTIFACTS
""",
    1,
)


class RunMessagesSummarization(SummarizationMiddleware):
    """Summarize on the size of the run's own messages only.

    The parent has a second trigger: it also summarizes whenever the model's reported `total_tokens` for
    the previous call passes the threshold. That total counts the system prompt and every tool schema,
    30k+ tokens for a bot with an MCP server, so it fired on every call, folded the model's fresh file
    reads into a summary each time, and the model read them again: a deterministic loop that ran until
    the model-call limit. `summary_trigger_tokens` means the run's messages, so that trigger is off."""

    def _should_summarize_based_on_reported_tokens(self, messages, threshold) -> bool:
        return False

    async def abefore_model(self, state, runtime):
        """Summarize as the parent does, then put the bot's saved todo list into the summary.

        The todo_write calls that built the list may be among the messages folded into the summary,
        and the system prompt only holds the list as it was when the run started."""
        update = await super().abefore_model(state, runtime)
        ctx = getattr(runtime, "context", None)
        if update is None or not isinstance(ctx, RunContext):
            return update
        async with ctx.services.session_factory() as session:
            todos = await load_todos(session, ctx.thread_id, ctx.actor_id)
        if not todos:
            return update
        section = todo_list_section(todos)
        messages = [
            m.model_copy(update={"content": f"{m.content}\n\n{section}"})
            if isinstance(m, HumanMessage) and m.additional_kwargs.get("lc_source") == "summarization"
            else m
            for m in update["messages"]
        ]
        return {**update, "messages": messages}


class Runner:
    def __init__(self, services) -> None:
        self.s = services

    def _model_price(self, bot: Actor) -> dict[str, float | None] | None:
        catalog = getattr(self.s, "model_catalog", None)
        if catalog is None:
            return None
        provider, model = effective_bot_profile(bot.bot, self.s.settings)
        result = getattr(catalog, "price_for", None)
        return result(provider, model) if result is not None else None

    async def _set_status(
        self,
        run_id: str,
        status: str,
        *,
        interrupt: dict | None = None,
        error: str | None = None,
        langsmith_run_id: str | None = None,
        usage: dict[str, int | float] | None = None,
    ) -> Run | None:
        async with self.s.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None:
                # Its row went away under a live run (a hard delete of the thread or bot). Updating
                # nothing beats an AttributeError that turns the run's ending into a crash.
                log.warning("run %s no longer exists; status %s not recorded", run_id, status)
                return None
            run.status, run.interrupt = status, interrupt
            if error is not None:
                run.error = error
            if langsmith_run_id:
                run.langsmith_run_id = langsmith_run_id
            if usage and usage.get("model_calls"):
                for k in (*USAGE_KEYS, "cost_usd"):
                    setattr(run, k, (getattr(run, k) or 0) + usage[k])
            if status == "running" and run.started_at is None:
                run.started_at = utcnow()
            if status in ("completed", "failed", "cancelled"):
                run.finished_at = utcnow()
            await activity.record(
                self.s,
                "run.status",
                session=session,
                level="error" if status == "failed" else "info",
                thread_id=run.thread_id,
                actor_id=run.actor_id,
                run_id=run.id,
                summary=f"run {status}"
                + (f": {error}" if error else "")
                + (f" ({interrupt.get('kind')})" if interrupt else ""),
                status=status,
                error=error,
                interrupt_kind=interrupt.get("kind") if interrupt else None,
                usage=usage,
                langsmith_run_id=langsmith_run_id,
            )
            await session.commit()
            await self.s.bus.publish("run.updated", run.thread_id, to_json(RunOut, run))
            if status in ("running", "waiting_human", "completed", "failed", "cancelled"):
                await self.s.bus.publish(
                    "bots.updated",
                    None,
                    {"id": run.actor_id, "active": status in ("running", "waiting_human")},
                )
            return run

    async def _reports_so_far(self, run_id: str) -> list[str]:
        async with self.s.session_factory() as session:
            rows = (await session.execute(select(RunEvent.payload).where(RunEvent.run_id == run_id, RunEvent.type == "text")
                                          .order_by(RunEvent.seq))).scalars().all()
        return [p["content"].strip() for p in rows if p.get("report")]

    async def _record(self, run: Run, seq: int, type_: str, payload: dict) -> int:
        async with self.s.session_factory() as session:
            ev = RunEvent(run_id=run.id, seq=seq, type=type_, payload=payload)
            session.add(ev)
            await session.commit()
            await self.s.bus.publish("run.event", run.thread_id, to_json(RunEventOut, ev))
        return seq + 1

    async def _next_seq(self, run_id: str) -> int:
        async with self.s.session_factory() as session:
            n = (
                await session.execute(
                    select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id)
                )
            ).scalar()
        return 0 if n is None else n + 1

    async def _system_message(self, thread_id: str, content: str) -> None:
        async with self.s.session_factory() as session:
            await post_message(self.s, session, thread_id=thread_id, sender=None, content=content)

    async def _post_interrupted(
        self, bot: Actor, thread: Thread, run: Run, hop: int, progress: RunProgress
    ) -> None:
        """Keep what a cancelled run had written: the reply still streaming, else the last finished turn.
        Not delivered, so a half-written @mention wakes nobody. Best-effort: the cancel must still land."""
        text = compose_reply(progress.reports, progress.streaming if progress.streaming.strip() else progress.reply)
        if not text.strip() and not progress.tool_calls:
            return
        try:
            async with self.s.session_factory() as session:
                # A cancel that lands while the finished reply is being posted must not post it twice.
                if (
                    await session.execute(
                        select(Message.id).where(Message.run_id == run.id).limit(1)
                    )
                ).first():
                    return
                res = await post_message(
                    self.s,
                    session,
                    thread_id=thread.id,
                    sender=bot,
                    content=text,
                    hop=hop,
                    run_id=run.id,
                    meta={"interrupted": True},
                    deliver=False,
                )
            await self._record(
                run, await self._next_seq(run.id), "message", {"message_id": res.message.id}
            )
        except Exception:
            log.exception("could not post the interrupted reply for run %s", run.id)

    async def _drop_checkpoint(self, run_id: str) -> None:
        """The agent transcript is checkpointed under the run id only so a `waiting_human` run can
        resume. Once the run is terminal nothing reads it again (reflection already holds its copy),
        so delete it rather than let `.langgraph.db` grow with every run ever made."""
        try:
            await self.s.checkpointer.adelete_thread(run_id)
        except Exception:
            log.exception("could not delete the checkpoint for run %s", run_id)

    async def _prepare(self, bot: Actor, thread: Thread, run: Run) -> tuple[str, dict, int]:
        st = self.s.settings
        async with self.s.session_factory() as session:
            all_actors = (await session.execute(select(Actor))).scalars().all()
            rows = (
                (
                    await session.execute(
                        select(Message)
                        .where(Message.thread_id == thread.id)
                        .order_by(Message.created_at.desc())
                        .limit(st.history_max_messages * 2)
                    )
                )
                .scalars()
                .all()
            )
            total = (
                await session.execute(
                    select(func.count()).select_from(Message).where(Message.thread_id == thread.id)
                )
            ).scalar() or 0
            parts = (
                (
                    await session.execute(
                        select(ThreadParticipant).where(ThreadParticipant.thread_id == thread.id)
                    )
                )
                .scalars()
                .all()
            )
            trigger_ids = [
                i.message_id
                for i in (
                    await session.execute(
                        select(InboxItem).where(
                            InboxItem.run_id == run.id, InboxItem.kind == "message"
                        )
                    )
                ).scalars()
                if i.message_id
            ]
            triggers = (
                (await session.execute(select(Message).where(Message.id.in_(trigger_ids))))
                .scalars()
                .all()
                if trigger_ids
                else []
            )
            # The list the bot saved with todo_write, so it carries over into this run.
            todos = (
                await load_todos(session, thread.id, bot.id)
                if "todo_write" in bot.bot.tool_names
                else []
            )
        by_id = {a.id: a for a in all_actors}
        by_handle = {a.handle: a for a in all_actors}
        participants = [by_id[p.actor_id].name for p in parts if p.actor_id in by_id]
        default_bot_handle = (
            by_id[thread.default_bot_actor_id].handle
            if thread.default_bot_actor_id in by_id
            else None
        )
        if default_bot_handle is None and DEFAULT_BOT_HANDLE in by_handle:
            default_bot_handle = DEFAULT_BOT_HANDLE
        # Who sees the whole thread: the default bot (it coordinates, so it needs the conversation) and the
        # only bot in a thread (nobody is delegating to it). Every other bot is a delegate and sees just the
        # messages addressed to it plus its own earlier replies: the hand-off has to be self-contained, and
        # read_history / recall_messages fetch the rest when it is not. Cuts each delegate call from
        # thread-sized to hand-off-sized, and keeps one bot's chatter out of another's context.
        bots_in_thread = {
            p.actor_id for p in parts if p.actor_id in by_id and by_id[p.actor_id].kind == "bot"
        }
        is_default = (
            default_bot_handle is not None
            and by_handle.get(default_bot_handle) is not None
            and by_handle[default_bot_handle].id == bot.id
        )
        scoped = not is_default and len(bots_in_thread) > 1
        trigger_ids = {m.id for m in triggers}
        if scoped:
            rows = [
                m
                for m in rows
                if m.sender_actor_id == bot.id
                or bot.id in (m.mentions or [])
                or m.id in trigger_ids
            ]
        history, older = build_history(
            list(rows),
            bot.id,
            token_budget=st.history_token_budget,
            max_messages=st.history_max_messages,
            trigger_ids=trigger_ids,
        )
        older += max(0, total - len(rows))
        query = "\n".join(m.content for m in triggers)
        memories = (
            await memory.relevant_memories(self.s.store, bot.id, query)
            if self.s.store is not None
            else []
        )
        workspace_root = thread_workspace_root(st.workspace_root, thread.working_directory)
        stable_prompt, dynamic_prompt = build_system_prompt_parts(
            bot=bot,
            all_bots=list(all_actors),
            participants=participants,
            memories=memories,
            workspace_root=str(workspace_root),
            older_count=older,
            # Only tools that will actually be bound: an MCP server that is down
            # must not be advertised, or the model calls a tool it does not have.
            tool_names=[n for n in bot.bot.tool_names if self.s.registry.has(n)],
            default_bot_handle=default_bot_handle,
            scoped=scoped,
            todos=todos,
        )
        prompt = SystemMessage(
            content=[
                {"type": "text", "text": stable_prompt},
                {"type": "text", "text": dynamic_prompt},
            ]
        )
        hop = max([m.hop for m in triggers], default=0) + 1
        return prompt, {"messages": history}, hop

    def model_call_limit(self, bot: Actor) -> int:
        """Model turns allowed per run: the bot's own `model_settings.max_model_calls`, else the global cap."""
        own = (bot.bot.model_settings or {}).get("max_model_calls")
        try:
            return max(1, int(own)) if own else int(self.s.settings.max_model_calls_per_run)
        except (TypeError, ValueError):
            return int(self.s.settings.max_model_calls_per_run)

    def recursion_limit(self, agent, bot: Actor) -> int:
        """Graph steps to allow: one per node per model turn, for one turn more than the call limit, plus
        room for the closing steps. Every middleware `before_model`/`after_model` hook is its own node."""
        nodes = [n for n in agent.get_graph().nodes if n not in ("__start__", "__end__")]
        return len(nodes) * (self.model_call_limit(bot) + 2) + 10

    def build_middleware(self, bot: Actor, model) -> list:
        """The run's context controls, in the order LangChain expects them to compose.

        Two tiers keep a long run's context from growing without bound. Summarization folds older
        history into one structured message once the context passes `summary_trigger_tokens`, keeping
        the last `summary_keep_messages` verbatim; it preserves decisions and file lists that plain
        clearing would lose. Context editing then clears tool results from turns before the last two,
        and their call arguments (e.g. the full content passed to write_file), once the context passes
        `context_trigger_tokens`, reclaiming at least `context_clear_at_least` per clearing. Each edit to earlier context costs a
        prompt-cache miss from that point, so both fire rarely and in large steps rather than a little
        on every turn. Editing runs after summarization so it respects what was already summarized.
        """
        st = self.s.settings
        p = bot.bot
        middleware = [
            # Retries transient upstream provider failures (rate limit, 5xx, "model stopped before
            # completing") so one bad provider turn does not abort the whole run. Before the cache
            # middleware: only the failing attempt pays, and the retried request is cache-warm.
            ModelRetryMiddleware(
                st.model_retry_max_attempts, st.model_retry_base_delay, st.model_retry_backoff_cap
            ),
            *caching_middleware(model, st),
            # Stops a run that keeps calling the model instead of answering; "end" posts a notice as the reply.
            ModelCallLimitMiddleware(run_limit=self.model_call_limit(bot), exit_behavior="end"),
            # Marks "error: ..." tool results as errors and ends a run stuck repeating one failing call.
            ToolFailureMiddleware(st.max_repeated_tool_failures, st.tool_output_cap),
            RunMessagesSummarization(
                model,
                trigger=("tokens", st.summary_trigger_tokens),
                keep=("messages", st.summary_keep_messages),
                summary_prompt=RUN_SUMMARY_PROMPT,
            ),
            ContextEditingMiddleware(
                edits=[
                    ClearOlderTurnsEdit(
                        trigger=st.context_trigger_tokens,
                        keep=0,
                        keep_turns=2,
                        clear_at_least=st.context_clear_at_least,
                        clear_tool_inputs=True,
                        exclude_tools=("ask_human", "manage_memory", "todo_write"),
                    )
                ]
            ),
        ]
        if p.approval_tools:
            middleware.append(
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        t: {"allowed_decisions": ["approve", "reject"]} for t in p.approval_tools
                    },
                    description_prefix="Tool execution requires approval",
                )
            )
        return middleware

    def _build_agent(self, bot: Actor, system_prompt: str):
        p = bot.bot
        tools = [
            *self.s.registry.resolve(list(p.tool_names)),
            *CORE_TOOLS,
            *SCHEDULING_TOOLS,
            *memory.memory_tools(bot.id, self.s.store),
            *builtin_tools(p, self.s.settings),
        ]
        model = self.s.model_factory(bot)
        return create_agent(
            model,
            tools=tools,
            system_prompt=system_prompt,
            middleware=self.build_middleware(bot, model),
            checkpointer=self.s.checkpointer,
            store=self.s.store,
            context_schema=RunContext,
        )

    async def _stream(
        self,
        agent,
        inputs,
        config,
        ctx: RunContext,
        run: Run,
        seq: int,
        progress: RunProgress | None = None,
        price: dict[str, float | None] | None = None,
    ) -> tuple[str, dict | None, int, dict[str, int | float]]:
        progress = progress if progress is not None else RunProgress()
        final_text, interrupt = "", None
        usage = empty_usage()
        # Middleware nodes that rewrite state (summarization: RemoveMessage(all) + summary + kept messages)
        # re-emit earlier AI messages in their update. Those are not new model calls: counting them again
        # tripled the usage totals, logged every old tool_call again and showed each reply twice in the UI.
        seen_replies: set[str] = set()
        async for mode, data in agent.astream(
            inputs, config=config, context=ctx, stream_mode=["messages", "updates"]
        ):
            if mode == "messages":
                token, meta = data
                if (
                    isinstance(token, AIMessageChunk)
                    and _text(token)
                    and meta.get("langgraph_node") == "model"
                ):
                    progress.streaming += _text(token)
                    await self.s.bus.publish(
                        "run.event",
                        run.thread_id,
                        {
                            "run_id": run.id,
                            "type": "text_delta",
                            "payload": {"delta": _text(token)},
                        },
                    )
                continue
            for source, update in data.items():
                if source == "__interrupt__":
                    interrupt = normalize_interrupt(update[0].value)
                    seq = await self._record(run, seq, "interrupt", interrupt)
                    await activity.record(
                        self.s,
                        "run.interrupt",
                        thread_id=run.thread_id,
                        actor_id=run.actor_id,
                        run_id=run.id,
                        summary=f"agent paused for a {interrupt.get('kind')}: {activity.preview(interrupt, 200)}",
                        kind=interrupt.get("kind"),
                        interrupt=activity.preview(interrupt),
                    )
                elif source == "tools" and isinstance(update, dict):
                    for m in update.get("messages", []):
                        if isinstance(m, ToolMessage):
                            log.info(
                                "run %s tool_result %s status=%s len=%d: %s",
                                run.id,
                                m.name,
                                m.status,
                                len(_text(m)),
                                _preview(_text(m)),
                            )
                            seq = await self._record(
                                run,
                                seq,
                                "tool_result",
                                {
                                    "tool_call_id": m.tool_call_id,
                                    "name": m.name,
                                    "status": m.status,
                                    "content": _text(m)[:TOOL_RESULT_CAP],
                                },
                            )
                            await activity.record(
                                self.s,
                                "run.tool_result",
                                level="warning" if m.status == "error" else "debug",
                                thread_id=run.thread_id,
                                actor_id=run.actor_id,
                                run_id=run.id,
                                summary=f"{m.name} -> {m.status} ({len(_text(m))} chars)",
                                name=m.name,
                                status=m.status,
                                chars=len(_text(m)),
                                content=activity.preview(_text(m)),
                            )
                elif isinstance(update, dict):
                    # "model" is the LLM turn; middleware nodes (e.g. the model-call limit ending the run with a
                    # notice) also emit AI messages, and those must become the reply too.
                    for m in update.get("messages", []):
                        if not isinstance(m, AIMessage):
                            continue
                        if m.id:
                            if m.id in seen_replies:
                                continue
                            seen_replies.add(m.id)
                        # Before any await: a cancel in between must find this turn, not the one before.
                        progress.streaming, progress.reply = "", _text(m) or progress.reply
                        progress.tool_calls += len(m.tool_calls)
                        inc = add_usage(usage, m, price)
                        if inc is not None:
                            log.info(
                                "run %s model call %d: prompt=%d (cache_read=%d) completion=%d",
                                run.id,
                                usage["model_calls"],
                                inc["prompt_tokens"],
                                inc["cache_read_tokens"],
                                inc["completion_tokens"],
                            )
                            # Persist each provider-reported turn before processing its tools. This keeps
                            # live run/thread/bot totals current and makes a tool round visible immediately.
                            await self._set_status(run.id, "running", usage=inc)
                        await activity.record(
                            self.s,
                            "run.model_call",
                            level="debug",
                            thread_id=run.thread_id,
                            actor_id=run.actor_id,
                            run_id=run.id,
                            summary=f"model replied: {len(m.tool_calls)} tool call(s), {len(_text(m))} chars of text",
                            tool_calls=[tc["name"] for tc in m.tool_calls],
                            text_chars=len(_text(m)),
                            usage=inc if self.s.settings.include_llm_call_details else None,
                            calls_so_far=usage["model_calls"],
                        )
                        for tc in m.tool_calls:
                            log.info(
                                "run %s tool_call %s(%s)", run.id, tc["name"], _preview(tc["args"])
                            )
                            seq = await self._record(
                                run,
                                seq,
                                "tool_call",
                                {"id": tc["id"], "name": tc["name"], "args": tc["args"]},
                            )
                            await activity.record(
                                self.s,
                                "run.tool_call",
                                level="debug",
                                thread_id=run.thread_id,
                                actor_id=run.actor_id,
                                run_id=run.id,
                                summary=f"{tc['name']}({activity.preview(tc['args'], 200)})",
                                name=tc["name"],
                                args=activity.preview(tc["args"]),
                            )
                        if _text(m):
                            final_text = _text(m)
                            report = bool(m.tool_calls) and len(final_text.strip()) >= REPORT_MIN_CHARS
                            if report:
                                progress.reports.append(final_text.strip())
                            seq = await self._record(run, seq, "text", {"content": final_text, "report": report})
        return final_text, interrupt, seq, usage

    async def execute(self, run_id: str, resume: Command | None = None) -> None:
        async with self.s.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None or run.status not in ("queued", "waiting_human"):
                return
            bot = await session.get(Actor, run.actor_id)
            thread = await session.get(Thread, run.thread_id)
        if thread is None or thread.deleted_at is not None:
            # Picked up in the window between the thread's delete closing its work and this run starting.
            await self._set_status(run.id, "cancelled", error="thread was deleted")
            await self._drop_checkpoint(run.id)
            return
        await self._set_status(run.id, "running")
        seq = await self._next_seq(run.id)
        if resume is not None:
            seq = await self._record(
                run, seq, "resumed", {"value": getattr(resume, "resume", None)}
            )
        # Pin the id of the trace's root run instead of reading one back afterwards: under LangGraph's
        # streaming the runs collect_runs() hands back each look like roots in memory (their parent is
        # only established server-side from dotted_order), so the first one is a nested ChatOpenAI call
        # and linking it drops the reader into the middle of the trace.
        trace_id = uuid.uuid4()
        config = {
            "configurable": {"thread_id": run.id},
            "metadata": {"bot": bot.handle, "thread_id": thread.id, "run_id": run.id},
            "run_name": f"bot:{bot.handle}",
            "run_id": trace_id,
        }
        started = time.monotonic()
        progress, hop = RunProgress(), 0
        if resume is not None:
            # A run paused on ask_human resumes in a fresh _stream; reports from before the pause belong
            # in its reply too.
            progress.reports = await self._reports_so_far(run.id)
        try:
            system_prompt, inputs, hop = await self._prepare(bot, thread, run)
            workspace_root = thread_workspace_root(
                self.s.settings.workspace_root, thread.working_directory
            )
            eff_provider, eff_model = effective_bot_profile(bot.bot, self.s.settings)
            log.info(
                "run %s started: bot=@%s thread=%s hop=%d resume=%s working_directory=%s tool_root=%s model=%s/%s tools=%s",
                run.id,
                bot.handle,
                thread.id,
                hop,
                resume is not None,
                thread.working_directory or ".",
                workspace_root,
                eff_provider,
                eff_model,
                ",".join(
                    [
                        *bot.bot.tool_names,
                        *(
                            t.get("name") or t["type"]
                            for t in builtin_tools(bot.bot, self.s.settings)
                        ),
                    ]
                )
                or "-",
            )
            # The text, not the message: its repr escapes every newline and backslash of the prompt.
            log.debug("run %s system prompt:\n%s", run.id, _text(system_prompt))
            await activity.record(
                self.s,
                "run.started",
                thread_id=thread.id,
                actor_id=bot.id,
                run_id=run.id,
                summary=f"@{bot.handle} run started (hop {hop}, {eff_provider}/{eff_model})"
                + (" resuming" if resume is not None else ""),
                hop=hop,
                resume=resume is not None,
                provider=eff_provider,
                model=eff_model,
                working_directory=thread.working_directory or ".",
                tool_root=str(workspace_root),
                tools=list(bot.bot.tool_names),
                history_messages=len(inputs.get("messages", [])),
                model_call_limit=self.model_call_limit(bot),
            )
            cli = adapter_for(bot.bot.provider)
            if cli is not None:
                # The turn runs in a coding agent CLI instead of create_agent (runtime/cli_agents).
                await execute_cli_turn(
                    self, cli, bot, thread, run, seq, system_prompt, inputs["messages"],
                    workspace_root, hop, progress, started,
                )
                return
            ctx = RunContext(
                bot.id,
                bot.handle,
                bot.name,
                thread.id,
                run.id,
                workspace_root,
                self.s,
                thread.working_directory,
                hop,
                tool_output_cap=self.s.settings.tool_output_cap,
                shell_output_cap=self.s.settings.shell_output_cap,
                shell_user=self.s.settings.shell_user,
            )
            agent = self._build_agent(bot, system_prompt)
            # The model-call limit is the real cap; the graph's recursion limit only has to be high enough
            # that the limit middleware ends the run first, and is derived from the graph so adding a
            # middleware hook (each is a node every turn traverses) can never make it the binding limit.
            config["recursion_limit"] = self.recursion_limit(agent, bot)
            with collect_runs() as cb:
                final_text, interrupt, seq, usage = await self._stream(
                    agent,
                    resume if resume is not None else inputs,
                    config,
                    ctx,
                    run,
                    seq,
                    progress,
                    self._model_price(bot),
                )
            ls_id = str(trace_id) if cb.traced_runs else None
            usage_line = (
                f"model_calls={usage['model_calls']} prompt_tokens={usage['prompt_tokens']} "
                f"cache_read_tokens={usage['cache_read_tokens']} completion_tokens={usage['completion_tokens']}"
            )
            if interrupt is not None:
                log.info(
                    "run %s waiting_human after %.1fs (%s): %s",
                    run.id,
                    time.monotonic() - started,
                    usage_line,
                    _preview(interrupt),
                )
                run = await self._set_status(
                    run.id, "waiting_human", interrupt=interrupt, langsmith_run_id=ls_id
                ) or run
                delivered = await deliver_question(self.s, run, interrupt)
                if not delivered:
                    # deliver_question only addresses human/external participants. A thread with none
                    # (e.g. a bot-to-bot delegation nobody added the human to) would otherwise leave this
                    # run "waiting_human" forever -- unresumable, and showing the bot as busy everywhere.
                    err = "ask_human has no human or external participant in this thread to ask"
                    log.warning("run %s waiting_human but undeliverable: %s", run.id, err)
                    await self._set_status(run.id, "failed", error=err)
                    await self._record(run, await self._next_seq(run.id), "error", {"error": err})
                    await self._system_message(
                        thread.id, f"@{bot.handle} tried to ask a question, but {err}."
                    )
                    await self._drop_checkpoint(run.id)
                return
            reply = compose_reply(progress.reports, final_text)
            if reply.strip():
                async with self.s.session_factory() as session:
                    res = await post_message(
                        self.s,
                        session,
                        thread_id=thread.id,
                        sender=bot,
                        content=reply,
                        mention_text=final_text,
                        hop=hop,
                        run_id=run.id,
                    )
                seq = await self._record(run, seq, "message", {"message_id": res.message.id})
            await self._set_status(run.id, "completed", langsmith_run_id=ls_id)
            log.info(
                "run %s completed in %.1fs: reply=%d chars %s langsmith_run_id=%s",
                run.id,
                time.monotonic() - started,
                len(final_text),
                usage_line,
                ls_id,
            )
            if bot.bot.memory_enabled and self.s.reflector is not None:
                # The run is already complete and its reply posted; reflection must never undo that.
                try:
                    state = await agent.aget_state(config)
                    self.s.reflector.schedule(
                        bot, list(state.values.get("messages", [])), thread_id=thread.id
                    )
                except Exception:
                    log.exception("could not schedule memory reflection for run %s", run.id)
            await self._drop_checkpoint(run.id)
        except asyncio.CancelledError:
            log.info("run %s cancelled after %.1fs", run.id, time.monotonic() - started)
            await self._post_interrupted(bot, thread, run, hop, progress)
            await self._set_status(run.id, "cancelled")
            await self._system_message(thread.id, f"@{bot.handle} run was cancelled.")
            await self._drop_checkpoint(run.id)
            raise
        except Exception as e:
            log.exception("run %s failed", run.id)
            err = (str(e) if isinstance(e, CliAgentError) else f"{type(e).__name__}: {e}")[:2000]
            # Status first: the bookkeeping below is best-effort and must never leave the run in "running".
            await self._set_status(run.id, "failed", error=err)
            try:
                # Re-read the sequence: events recorded inside _stream are not visible to `seq` here.
                await self._record(run, await self._next_seq(run.id), "error", {"error": err})
            except Exception:
                log.exception("could not record the error event for run %s", run.id)
            try:
                await self._system_message(thread.id, f"@{bot.handle} failed: {err}")
            except Exception:
                log.exception("could not post the failure notice for run %s", run.id)
            await self._drop_checkpoint(run.id)
