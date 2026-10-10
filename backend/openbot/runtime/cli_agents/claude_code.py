"""Claude Code: `claude -p --output-format stream-json`."""
from __future__ import annotations

import json
import ntpath
import posixpath
import re
from collections.abc import Mapping
from typing import Any

from openbot.runtime.cli_agents.base import (
    EDIT,
    READ_ONLY,
    CliAdapter,
    CliAgentError,
    StreamParser,
    Turn,
    TurnResult,
    UnknownSession,
)

# A permission mode alone does not make a level true to its name: `dontAsk` only denies what would prompt,
# so an allow rule in the user's own Claude settings (Edit, Bash(*)) still applies, and `acceptEdits` runs
# with every tool and MCP server of that setup. Both levels therefore run in restricted mode with an
# explicit tool list: no tool that runs commands, the settings files and MCP servers ignored (which also
# keeps the working directory's hooks and .mcp.json out, since `claude -p` shows no trust dialog), and the
# file tools confined to the working directory. bypassPermissions is deliberately not mapped.
_RESTRICTED = ("--restricted", "--strict-mcp-config", "--tools")
_PERMISSION_ARGS = {
    READ_ONLY: ("--permission-mode", "dontAsk", *_RESTRICTED, "Read,Grep,Glob"),
    EDIT: ("--permission-mode", "acceptEdits", *_RESTRICTED, "Read,Grep,Glob,Edit,Write,NotebookEdit"),
}
_UNKNOWN_SESSION = re.compile(r"no conversation found with session id|session .{0,80} not found|--resume requires a valid session",
                              re.IGNORECASE)


def _n(d: dict, key: str) -> int:
    v = d.get(key)
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _cost(d: dict, key: str) -> float:
    v = d.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


_COUNTERS = ("input", "cache_write", "cache_read", "output", "thinking")


def session_totals(result: dict) -> dict | None:
    """`modelUsage` and `total_cost_usd` count the whole session: on a resumed turn they contain every
    earlier turn again."""
    entries = [v for v in (result.get("modelUsage") or {}).values() if isinstance(v, dict)]
    if not entries:
        return None
    return {"input": sum(_n(e, "inputTokens") for e in entries),
            "cache_write": sum(_n(e, "cacheCreationInputTokens") for e in entries),
            "cache_read": sum(_n(e, "cacheReadInputTokens") for e in entries),
            "output": sum(_n(e, "outputTokens") for e in entries),
            "thinking": sum(_n(e, "thinkingTokens") for e in entries),
            "cost": _cost(result, "total_cost_usd")}


def result_usage(result: dict, baseline: dict | None = None) -> dict[str, int | float]:
    """This invocation's usage in the run's usage keys: the session totals minus `baseline`, the totals
    the same session had after its previous turn. The top-level `usage` is per invocation and serves as
    the check: a difference smaller than it means the CLI did not count per session after all, and the
    totals are taken as they are. The per-message usage on the assistant events is never added up.

    Prompt tokens count cache writes and reads, as for Anthropic. The cost is the CLI's own figure, at
    API prices, also when a subscription login pays for it."""
    u = result.get("usage") or {}
    own = {"input": _n(u, "input_tokens"), "cache_write": _n(u, "cache_creation_input_tokens"),
           "cache_read": _n(u, "cache_read_input_tokens"), "output": _n(u, "output_tokens"),
           "thinking": _n(u.get("output_tokens_details") or {}, "thinking_tokens"),
           "cost": _cost(result, "total_cost_usd")}
    count = session_totals(result) or own
    if baseline and count is not own:
        rest = {k: count[k] - _n(baseline, k) for k in _COUNTERS}
        if all(rest[k] >= own[k] for k in _COUNTERS if k != "thinking"):
            count = {**rest, "cost": max(0.0, count["cost"] - _cost(baseline, "cost"))}
    prompt = count["input"] + count["cache_write"] + count["cache_read"]
    return {"prompt_tokens": prompt, "completion_tokens": count["output"], "cache_read_tokens": count["cache_read"],
            "cache_write_tokens": count["cache_write"], "reasoning_tokens": count["thinking"],
            "total_tokens": prompt + count["output"], "model_calls": max(1, _n(result, "num_turns")),
            "cost_usd": count["cost"]}


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) if isinstance(b, dict) and b.get("type") == "text"
                         else f"[{b.get('type', 'block')}]" if isinstance(b, dict) else str(b) for b in content)
    return "" if content is None else json.dumps(content, default=str)


class ClaudeStream(StreamParser):
    def __init__(self, session_id_re: re.Pattern[str]) -> None:
        self._session_id_re = session_id_re
        self.session_id: str | None = None
        self.result: dict | None = None
        self.texts: list[str] = []
        self._tool_names: dict[str, str] = {}

    def feed(self, event: dict) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        sid = event.get("session_id")
        if isinstance(sid, str) and sid != self.session_id and self._session_id_re.match(sid):
            self.session_id = sid
            out.append(("session", sid))
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            # What the CLI says about itself; apiKeySource names where its credential came from, not the key.
            out.append(("init", {k: event[k] for k in ("model", "permissionMode", "apiKeySource") if isinstance(event.get(k), str)}))
        # Messages of a subagent carry the id of the tool call that started it; its text is not the reply.
        main_chain = not event.get("parent_tool_use_id")
        if kind == "stream_event" and main_chain:
            ev = event.get("event") or {}
            delta = ev.get("delta") or {}
            if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta" and delta.get("text"):
                out.append(("delta", delta["text"]))
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and main_chain and str(block.get("text", "")).strip():
                    self.texts.append(block["text"])
                    out.append(("text", block["text"]))
                elif block.get("type") == "tool_use":
                    call_id, name = str(block.get("id", "")), str(block.get("name", "tool"))
                    self._tool_names[call_id] = name
                    out.append(("tool_call", {"id": call_id, "name": name, "args": block.get("input") or {}}))
        elif kind == "user":
            content = (event.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    call_id = str(block.get("tool_use_id", ""))
                    out.append(("tool_result", {"tool_call_id": call_id, "name": self._tool_names.get(call_id, "tool"),
                                                "status": "error" if block.get("is_error") else "success",
                                                "content": _tool_result_text(block.get("content"))}))
        elif kind == "result":
            self.result = event
        return out

    def usage_so_far(self) -> dict[str, int | float] | None:
        return result_usage(self.result) if self.result else None

    def finish(self, *, exit_code: int, stderr: str, resumed: bool, baseline: dict | None) -> TurnResult:
        result = self.result
        if result is None:
            if resumed and _UNKNOWN_SESSION.search(stderr):
                raise UnknownSession
            detail = stderr.strip()[-1000:]
            raise CliAgentError(f"error: claude exited with code {exit_code} without a result" + (f": {detail}" if detail else ""))
        text = str(result.get("result") or "")
        subtype = str(result.get("subtype") or "")
        if result.get("is_error") or subtype.startswith("error"):
            errors = " ".join(str(e) for e in result.get("errors") or [])
            if resumed and _UNKNOWN_SESSION.search(f"{text} {errors} {stderr}"):
                raise UnknownSession
            detail = (text or errors or stderr.strip())[-1000:]
            raise CliAgentError(f"error: claude run failed ({subtype or 'error'})" + (f": {detail}" if detail else ""),
                                usage=result_usage(result, baseline), totals=session_totals(result))
        return TurnResult(text=text or (self.texts[-1] if self.texts else ""), usage=result_usage(result, baseline),
                          session_id=self.session_id, totals=session_totals(result))


class ClaudeCode(CliAdapter):
    provider = "claude-code"
    label = "Claude Code"
    binary = "claude"
    path_setting = "claude_code_path"
    install_hint = "Install it (https://code.claude.com), log in once in a terminal, then restart OpenBot."
    # The first release with `--restricted` (its changelog), which both permission levels rely on.
    min_version = (2, 1, 248)
    update_hint = "Update it with `claude update`."
    status_argv = ("auth", "status")
    login_hint = "Run `claude auth login` in a terminal."

    def install_dirs(self, *, home: str, env: Mapping[str, str], win: bool) -> list[str]:
        p = ntpath if win else posixpath
        if not win:
            return [p.join(home, ".local", "bin", "claude"), p.join(home, ".claude", "local", "claude"),
                    p.join(home, ".npm-global", "bin", "claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
        found = [p.join(home, ".local", "bin", "claude.exe"), p.join(home, ".claude", "local", "claude.exe"),
                 p.join(home, ".claude", "local", "claude.cmd")]
        if env.get("APPDATA"):
            found.append(p.join(env["APPDATA"], "npm", "claude.cmd"))
        if env.get("LOCALAPPDATA"):
            found.append(p.join(env["LOCALAPPDATA"], "Microsoft", "WinGet", "Links", "claude.exe"))
        return [*found, p.join(home, "scoop", "shims", "claude.exe")]

    def argv(self, executable: str, turn: Turn) -> list[str]:
        argv = [executable, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--append-system-prompt-file", turn.system_prompt_file, *_PERMISSION_ARGS[turn.permission]]
        if turn.model:
            argv += ["--model", turn.model]
        if turn.session_id:
            argv += ["--resume", turn.session_id]
        return argv

    def parser(self) -> ClaudeStream:
        return ClaudeStream(self.session_id_re)
