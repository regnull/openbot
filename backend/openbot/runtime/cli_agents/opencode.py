"""OpenCode: `opencode run --format json` (one JSON object per stdout line)."""
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

# In non-interactive `run` a permission request is never asked: it is auto-rejected (and the model is
# told so). --auto would allow everything including running commands, so the permission levels are set
# with OPENCODE_PERMISSION instead, which merges after the user's own config. Denies are explicit so an
# allow rule elsewhere cannot widen the bot's reach; external_directory stays readable (the Read tool is
# the point of read-only) and lsp is diagnostics.
_COMMON = {"read": "allow", "glob": "allow", "grep": "allow", "list": "allow", "lsp": "allow",
           "external_directory": "allow", "edit": "deny", "bash": "deny", "task": "deny",
           "webfetch": "deny", "websearch": "deny", "skill": "deny"}
_PERMISSIONS = {READ_ONLY: _COMMON, EDIT: {**_COMMON, "edit": "allow"}}
# Ancient versions refused --session (Session not found); 2.x creates the session if it is gone.
_UNKNOWN_SESSION = re.compile(r"session not found", re.IGNORECASE)


def _n(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _f(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _result_text(state: dict) -> str:
    out = state.get("output")
    if isinstance(out, str):
        return out
    blocks = (state.get("metadata") or {}).get("content")
    if isinstance(blocks, list):
        return "\n".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    return "" if out is None else json.dumps(out, default=str)


def usage_of(steps: int, tokens: dict, cost: float) -> dict[str, int | float]:
    """Usage of the finished steps. `--format json` reports usage per step in `step_finish` events and
    not at the end, so the leaves' tokens are counted here; the last step (the reply) may never send
    its step-finish, which is why the totals can be slightly under what the run really cost."""
    prompt = _n(tokens.get("input")) + _n(tokens.get("cache_read")) + _n(tokens.get("cache_write"))
    output = _n(tokens.get("output")) + _n(tokens.get("reasoning"))
    return {"prompt_tokens": prompt, "completion_tokens": output, "cache_read_tokens": _n(tokens.get("cache_read")),
            "cache_write_tokens": _n(tokens.get("cache_write")), "reasoning_tokens": _n(tokens.get("reasoning")),
            "total_tokens": prompt + output, "model_calls": max(1, steps), "cost_usd": cost}


class OpenCodeStream(StreamParser):
    """Cards: step_start begins one model turn, text is streamed whole, tool_use carries the part with
    its state (pending = call, completed/error = result), and step_finish carries that step's tokens.
    A failure prints a single `error` event."""

    def __init__(self, session_id_re: re.Pattern[str]) -> None:
        self._session_id_re = session_id_re
        self.session_id: str | None = None
        self.texts: list[str] = []
        self._seen: set[str] = set()
        self.errors: list[str] = []
        self.steps = 0
        self._tokens: dict[str, int] = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
        self._cost = 0.0

    def feed(self, event: dict) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        sid = event.get("sessionID")
        if isinstance(sid, str) and sid and sid != self.session_id and self._session_id_re.match(sid):
            self.session_id = sid
            out.append(("session", sid))
        kind = event.get("type")
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        if kind == "error":
            message = (event.get("error") or {}).get("message")
            if isinstance(message, str) and message:
                self.errors.append(message)
        elif kind == "text":
            text = str(part.get("text", ""))
            if text.strip():
                self.texts.append(text)
                out.append(("text", text))
        elif kind == "step_start":
            self.steps += 1
        elif kind == "step_finish":
            tokens = (part.get("tokens") or {}) if isinstance(part.get("tokens"), dict) else {}
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            for key in ("input", "output", "reasoning"):
                self._tokens[key] += _n(tokens.get(key))
            for key in ("read", "write"):
                self._tokens[f"cache_{key}"] += _n(cache.get(key))
            self._cost += _f(part.get("cost"))
        elif kind == "tool_use" and part.get("type") == "tool":
            state = (part.get("state") or {}) if isinstance(part.get("state"), dict) else {}
            call_id, name = str(part.get("id", "")), str(part.get("tool", "tool"))
            status = str(state.get("status", ""))
            if status == "pending":
                out.append(("tool_call", {"id": call_id, "name": name, "args": (state.get("input") or {})}))
                self._seen.add(call_id)
            elif status in ("completed", "error"):
                call = None if call_id in self._seen else {"id": call_id, "name": name,
                                                           "args": (state.get("input") or {})}
                result = ("tool_result", {"tool_call_id": call_id, "name": name,
                                          "status": "error" if status == "error" else "success",
                                          "content": _result_text(state)})
                self._seen.add(call_id)
                if call:
                    out.append(("tool_call", call))
                out.append(result)
        return out

    def usage_so_far(self) -> dict[str, int | float] | None:
        return usage_of(self.steps, self._tokens, self._cost) if self.steps else None

    def finish(self, *, exit_code: int, stderr: str, resumed: bool, baseline: dict | None) -> TurnResult:
        errors = " ".join(e for e in self.errors if e)
        detail = (errors or stderr.strip())[-1000:]
        if exit_code != 0 or self.errors:
            if resumed and _UNKNOWN_SESSION.search(detail):
                raise UnknownSession
            raise CliAgentError(f"error: opencode run failed (exit {exit_code})" + (f": {detail}" if detail else ""),
                                usage=usage_of(self.steps, self._tokens, self._cost))
        return TurnResult(text="\n\n".join(self.texts), usage=usage_of(self.steps, self._tokens, self._cost),
                          session_id=self.session_id)


class OpenCode(CliAdapter):
    provider = "opencode"
    label = "OpenCode"
    binary = "opencode"
    path_setting = "opencode_path"
    install_hint = "Install it (https://opencode.ai), log in once in a terminal (`opencode auth login`), then restart OpenBot."
    status_argv = ()
    login_hint = "Run `opencode auth login` in a terminal."
    session_id_re = re.compile(r"^ses_[A-Za-z0-9_-]{8,64}$")

    def install_dirs(self, *, home: str, env: Mapping[str, str], win: bool) -> list[str]:
        p = ntpath if win else posixpath
        if not win:
            return [p.join(home, ".opencode", "bin", "opencode"), p.join(home, ".local", "bin", "opencode"),
                    "/usr/local/bin/opencode", "/opt/homebrew/bin/opencode"]
        found = [p.join(home, ".opencode", "bin", "opencode.exe")]
        if env.get("APPDATA"):
            found.append(p.join(env["APPDATA"], "npm", "opencode.cmd"))
        if env.get("LOCALAPPDATA"):
            found.append(p.join(env["LOCALAPPDATA"], "Programs", "opencode", "opencode.exe"))
        return found

    def argv(self, executable: str, turn: Turn) -> list[str]:
        argv = [executable, "run", "--format", "json"]
        if turn.model:
            argv += ["--model", turn.model]
        if turn.session_id:
            argv += ["--session", turn.session_id]
        return argv

    def parser(self) -> OpenCodeStream:
        return OpenCodeStream(self.session_id_re)

    def turn_env(self, turn: Turn) -> dict[str, str]:
        return {"OPENCODE_PERMISSION": json.dumps(_PERMISSIONS[turn.permission])}
