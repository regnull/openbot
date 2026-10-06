"""Tool failures as failures, and a stop for a bot that keeps repeating one.

Tools report a failure by returning text that starts with "error:" (the built-ins and the MCP wrapper
both do, so a bad call is something the model can react to rather than an exception that fails the
run). That text reached the model, but the ToolMessage still said status="success": the run card showed
every call as fine and the activity log never recorded a failed tool at warning level.

`ToolFailureMiddleware` does two things:

- It marks an "error: ..." result as status="error". When the model repeats a call it already made,
  with the same arguments and getting the same error, it appends a note telling the model to change the
  call instead of retrying it.
- Before each model turn it counts identical failures (same tool, same arguments, same error) in the
  run. Once one reaches `max_repeats` it ends the run and posts the failing call and its error as the
  reply. Without this, a bot stuck retrying an MCP call it filled in wrongly ran until the generic model
  call limit stopped it, and the limit notice did not say what went wrong.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage

REPEAT_NOTE = ("\n\n[This exact call already failed with this same error. Do not retry it unchanged: "
               "change the arguments, use another tool, or report the failure.]")
REPEAT_CALL_NOTE = ("\n\n[This exact call has been repeated several times. Do not repeat it unchanged: "
                    "use the result you have, change the arguments, or use another tool.]")


def _text(m: ToolMessage) -> str:
    c = m.content
    if isinstance(c, str):
        return c
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c)


def _clip(s: str, limit: int = 800) -> str:
    return s if len(s) <= limit else s[:limit] + "…"


def is_failure(m: ToolMessage) -> bool:
    return m.status == "error" or _text(m).lstrip().lower().startswith("error:")


def _signature(name: str, args: Any, error: str) -> tuple[str, str, str]:
    return name, json.dumps(args, sort_keys=True, default=str), error


def _failures(messages: list) -> Counter:
    """Count failed calls in `messages` by (tool, arguments, error)."""
    calls: dict[str, tuple[str, Any]] = {}
    counts: Counter = Counter()
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                calls[tc["id"]] = (tc["name"], tc["args"])
        elif isinstance(m, ToolMessage) and m.tool_call_id in calls and is_failure(m):
            name, args = calls[m.tool_call_id]
            counts[_signature(name, args, _text(m).removesuffix(REPEAT_CALL_NOTE).removesuffix(REPEAT_NOTE))] += 1
    return counts


# Adapted from OpenCode's doom-loop check (MIT-licensed), which detects repeated tool calls.
def _consecutive_calls(messages: list) -> tuple[tuple[str, str] | None, int]:
    """Return the latest tool-call signature and its consecutive count."""
    calls: dict[str, tuple[str, Any]] = {}
    completed: list[tuple[str, str]] = []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                calls[tc["id"]] = (tc["name"], tc["args"])
        elif isinstance(m, ToolMessage) and m.tool_call_id in calls:
            name, args = calls[m.tool_call_id]
            completed.append((name, json.dumps(args, sort_keys=True, default=str)))
    if not completed:
        return None, 0
    latest = completed[-1]
    count = 0
    for call in reversed(completed):
        if call != latest:
            break
        count += 1
    return latest, count


class ToolFailureMiddleware(AgentMiddleware):
    """Marks "error: ..." tool results as errors and ends a run stuck repeating one failing call."""

    def __init__(self, max_repeats: int) -> None:
        super().__init__()
        self.max_repeats = max_repeats   # 0 turns the stop off; failures are still marked

    def _mark(self, request, result):
        if not isinstance(result, ToolMessage):
            return result
        tc = request.tool_call
        messages = (request.state or {}).get("messages", []) if isinstance(request.state, dict) else []
        if is_failure(result):
            result.status = "error"
            if _failures(messages)[_signature(tc["name"], tc["args"], _text(result))]:
                result.content = _text(result) + REPEAT_NOTE
        previous, consecutive = _consecutive_calls(messages)
        signature = (tc["name"], json.dumps(tc["args"], sort_keys=True, default=str))
        if self.max_repeats > 0 and previous == signature and consecutive >= self.max_repeats - 1:
            result.content = _text(result) + REPEAT_CALL_NOTE
        return result

    def wrap_tool_call(self, request, handler):
        return self._mark(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._mark(request, await handler(request))

    def _check(self, state) -> dict[str, Any] | None:
        if self.max_repeats <= 0:
            return None
        messages = state.get("messages", [])
        repeated = [(sig, n) for sig, n in _failures(messages).items() if n >= self.max_repeats]
        if repeated:
            (name, args, error), n = repeated[0]
            notice = (f"Stopped: `{name}` failed {n} times with the same arguments and the same error, so this run "
                      f"ended instead of retrying it again.\n\nArguments: {_clip(args)}\n\n{_clip(error)}")
            return {"jump_to": "end", "messages": [AIMessage(content=notice)]}
        signature, count = _consecutive_calls(messages)
        if signature and count > self.max_repeats:
            name, args = signature
            notice = (f"Stopped: `{name}` was called {count} times consecutively with the same arguments, so this run "
                      "ended instead of repeating it again.\n\nArguments: " + _clip(args))
            return {"jump_to": "end", "messages": [AIMessage(content=notice)]}
        return None

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime) -> dict[str, Any] | None:
        return self._check(state)

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return self._check(state)
