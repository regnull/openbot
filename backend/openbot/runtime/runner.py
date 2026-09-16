from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
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
from openbot.runtime import memory
from openbot.runtime.delivery import DEFAULT_BOT_HANDLE, deliver_question, post_message
from openbot.runtime.prompt import build_history, build_system_prompt
from openbot.runtime.providers import effective_bot_profile
from openbot.tools.builtin.core import CORE_TOOLS
from openbot.tools.builtin.workspace import thread_workspace_root
from openbot.tools.context import RunContext

log = logging.getLogger(__name__)
TOOL_RESULT_CAP = 4000
LOG_PREVIEW_CAP = 500


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
            return {"kind": "approval", "actions": [{"name": a.get("name"), "args": a.get("args", {})} for a in value["action_requests"]]}
    return {"kind": "question", "question": str(value)}


def _text(m) -> str:
    # langchain-core >= 1.6 exposes .text as a str-like accessor; older versions as a method.
    t = getattr(m, "text", None)
    if isinstance(t, str):
        return str(t)
    return t() if callable(t) else ""


class Runner:
    def __init__(self, services) -> None:
        self.s = services

    async def _set_status(self, run_id: str, status: str, *, interrupt: dict | None = None, error: str | None = None,
                          langsmith_run_id: str | None = None) -> Run:
        async with self.s.session_factory() as session:
            run = await session.get(Run, run_id)
            run.status, run.interrupt = status, interrupt
            if error is not None:
                run.error = error
            if langsmith_run_id:
                run.langsmith_run_id = langsmith_run_id
            if status == "running" and run.started_at is None:
                run.started_at = utcnow()
            if status in ("completed", "failed", "cancelled"):
                run.finished_at = utcnow()
            await session.commit()
            await self.s.bus.publish("run.updated", run.thread_id, to_json(RunOut, run))
            if status in ("running", "waiting_human", "completed", "failed", "cancelled"):
                await self.s.bus.publish("bots.updated", None, {"id": run.actor_id, "active": status in ("running", "waiting_human")})
            return run

    async def _record(self, run: Run, seq: int, type_: str, payload: dict) -> int:
        async with self.s.session_factory() as session:
            ev = RunEvent(run_id=run.id, seq=seq, type=type_, payload=payload)
            session.add(ev)
            await session.commit()
            await self.s.bus.publish("run.event", run.thread_id, to_json(RunEventOut, ev))
        return seq + 1

    async def _next_seq(self, run_id: str) -> int:
        async with self.s.session_factory() as session:
            n = (await session.execute(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id))).scalar()
        return 0 if n is None else n + 1

    async def _system_message(self, thread_id: str, content: str) -> None:
        async with self.s.session_factory() as session:
            await post_message(self.s, session, thread_id=thread_id, sender=None, content=content)

    async def _prepare(self, bot: Actor, thread: Thread, run: Run) -> tuple[str, dict, int]:
        st = self.s.settings
        async with self.s.session_factory() as session:
            all_actors = (await session.execute(select(Actor))).scalars().all()
            rows = (await session.execute(select(Message).where(Message.thread_id == thread.id)
                                          .order_by(Message.created_at.desc()).limit(st.history_max_messages * 2))).scalars().all()
            total = (await session.execute(select(func.count()).select_from(Message).where(Message.thread_id == thread.id))).scalar() or 0
            parts = (await session.execute(select(ThreadParticipant).where(ThreadParticipant.thread_id == thread.id))).scalars().all()
            trigger_ids = [i.message_id for i in (await session.execute(select(InboxItem).where(InboxItem.run_id == run.id, InboxItem.kind == "message"))).scalars() if i.message_id]
            triggers = (await session.execute(select(Message).where(Message.id.in_(trigger_ids)))).scalars().all() if trigger_ids else []
        history, older = build_history(list(rows), bot.id, token_budget=st.history_token_budget, max_messages=st.history_max_messages)
        older += max(0, total - len(rows))
        by_id = {a.id: a for a in all_actors}
        by_handle = {a.handle: a for a in all_actors}
        participants = [by_id[p.actor_id].name for p in parts if p.actor_id in by_id]
        default_bot_handle = by_id[thread.default_bot_actor_id].handle if thread.default_bot_actor_id in by_id else None
        if default_bot_handle is None and DEFAULT_BOT_HANDLE in by_handle:
            default_bot_handle = DEFAULT_BOT_HANDLE
        query = "\n".join(m.content for m in triggers)
        memories = await memory.relevant_memories(self.s.store, bot.id, query) if self.s.store is not None else []
        workspace_root = thread_workspace_root(st.workspace_root, thread.working_directory)
        prompt = build_system_prompt(bot=bot, all_bots=list(all_actors), participants=participants, memories=memories,
                                     workspace_root=str(workspace_root), older_count=older,
                                     tool_names=list(bot.bot.tool_names), default_bot_handle=default_bot_handle)
        hop = max([m.hop for m in triggers], default=0) + 1
        return prompt, {"messages": history}, hop

    def _build_agent(self, bot: Actor, system_prompt: str):
        p = bot.bot
        tools = [*self.s.registry.resolve(list(p.tool_names)), *CORE_TOOLS, *memory.memory_tools(bot.id, self.s.store)]
        middleware = []
        if p.approval_tools:
            middleware.append(HumanInTheLoopMiddleware(
                interrupt_on={t: {"allowed_decisions": ["approve", "reject"]} for t in p.approval_tools},
                description_prefix="Tool execution requires approval"))
        return create_agent(self.s.model_factory(bot), tools=tools, system_prompt=system_prompt, middleware=middleware,
                            checkpointer=self.s.checkpointer, store=self.s.store, context_schema=RunContext)

    async def _stream(self, agent, inputs, config, ctx: RunContext, run: Run, seq: int) -> tuple[str, dict | None, int]:
        final_text, interrupt = "", None
        async for mode, data in agent.astream(inputs, config=config, context=ctx, stream_mode=["messages", "updates"]):
            if mode == "messages":
                token, meta = data
                if isinstance(token, AIMessageChunk) and _text(token) and meta.get("langgraph_node") == "model":
                    await self.s.bus.publish("run.event", run.thread_id, {"run_id": run.id, "type": "text_delta", "payload": {"delta": _text(token)}})
                continue
            for source, update in data.items():
                if source == "__interrupt__":
                    interrupt = normalize_interrupt(update[0].value)
                    seq = await self._record(run, seq, "interrupt", interrupt)
                elif source == "model" and isinstance(update, dict):
                    for m in update.get("messages", []):
                        if not isinstance(m, AIMessage):
                            continue
                        for tc in m.tool_calls:
                            log.info("run %s tool_call %s(%s)", run.id, tc["name"], _preview(tc["args"]))
                            seq = await self._record(run, seq, "tool_call", {"id": tc["id"], "name": tc["name"], "args": tc["args"]})
                        if _text(m):
                            final_text = _text(m)
                            seq = await self._record(run, seq, "text", {"content": final_text})
                elif source == "tools" and isinstance(update, dict):
                    for m in update.get("messages", []):
                        if isinstance(m, ToolMessage):
                            log.info("run %s tool_result %s status=%s len=%d: %s", run.id, m.name, m.status, len(_text(m)), _preview(_text(m)))
                            seq = await self._record(run, seq, "tool_result", {"tool_call_id": m.tool_call_id, "name": m.name,
                                                                              "status": m.status, "content": _text(m)[:TOOL_RESULT_CAP]})
        return final_text, interrupt, seq

    async def execute(self, run_id: str, resume: Command | None = None) -> None:
        async with self.s.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None or run.status not in ("queued", "waiting_human"):
                return
            bot = await session.get(Actor, run.actor_id)
            thread = await session.get(Thread, run.thread_id)
        await self._set_status(run.id, "running")
        seq = await self._next_seq(run.id)
        if resume is not None:
            seq = await self._record(run, seq, "resumed", {"value": getattr(resume, "resume", None)})
        # Pin the id of the trace's root run instead of reading one back afterwards: under LangGraph's
        # streaming the runs collect_runs() hands back each look like roots in memory (their parent is
        # only established server-side from dotted_order), so the first one is a nested ChatOpenAI call
        # and linking it drops the reader into the middle of the trace.
        trace_id = uuid.uuid4()
        config = {"configurable": {"thread_id": run.id}, "metadata": {"bot": bot.handle, "thread_id": thread.id, "run_id": run.id},
                  "run_name": f"bot:{bot.handle}", "run_id": trace_id}
        started = time.monotonic()
        try:
            system_prompt, inputs, hop = await self._prepare(bot, thread, run)
            workspace_root = thread_workspace_root(self.s.settings.workspace_root, thread.working_directory)
            eff_provider, eff_model = effective_bot_profile(bot.bot, self.s.settings)
            log.info("run %s started: bot=@%s thread=%s hop=%d resume=%s working_directory=%s tool_root=%s model=%s/%s tools=%s",
                     run.id, bot.handle, thread.id, hop, resume is not None, thread.working_directory or ".",
                     workspace_root, eff_provider, eff_model, ",".join(bot.bot.tool_names) or "-")
            log.debug("run %s system prompt:\n%s", run.id, system_prompt)
            ctx = RunContext(bot.id, bot.handle, bot.name, thread.id, run.id, workspace_root, self.s,
                             thread.working_directory, hop)
            agent = self._build_agent(bot, system_prompt)
            with collect_runs() as cb:
                final_text, interrupt, seq = await self._stream(agent, resume if resume is not None else inputs, config, ctx, run, seq)
            ls_id = str(trace_id) if cb.traced_runs else None
            if interrupt is not None:
                log.info("run %s waiting_human after %.1fs: %s", run.id, time.monotonic() - started, _preview(interrupt))
                run = await self._set_status(run.id, "waiting_human", interrupt=interrupt, langsmith_run_id=ls_id)
                await deliver_question(self.s, run, interrupt)
                return
            if final_text.strip():
                async with self.s.session_factory() as session:
                    res = await post_message(self.s, session, thread_id=thread.id, sender=bot, content=final_text, hop=hop, run_id=run.id)
                seq = await self._record(run, seq, "message", {"message_id": res.message.id})
            await self._set_status(run.id, "completed", langsmith_run_id=ls_id)
            log.info("run %s completed in %.1fs: reply=%d chars langsmith_run_id=%s", run.id, time.monotonic() - started,
                     len(final_text), ls_id)
            if bot.bot.memory_enabled and self.s.reflector is not None:
                # The run is already complete and its reply posted; reflection must never undo that.
                try:
                    state = await agent.aget_state(config)
                    self.s.reflector.schedule(bot, list(state.values.get("messages", [])))
                except Exception:
                    log.exception("could not schedule memory reflection for run %s", run.id)
        except asyncio.CancelledError:
            log.info("run %s cancelled after %.1fs", run.id, time.monotonic() - started)
            await self._set_status(run.id, "cancelled")
            await self._system_message(thread.id, f"@{bot.handle} run was cancelled.")
            raise
        except Exception as e:
            log.exception("run %s failed", run.id)
            err = f"{type(e).__name__}: {e}"[:2000]
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
