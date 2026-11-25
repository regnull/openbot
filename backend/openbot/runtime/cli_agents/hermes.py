"""Hermes: `hermes chat --format stream-json --query-file -` (one JSON object per stdout line)."""
from __future__ import annotations

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

# `-t` takes hermes toolset names only (a bare tool name fails with invalid_params). There is no
# read-only file toolset, so those are the closest read-only toolsets: web search, image analysis,
# todo planning and session search — no file tools at all. EDIT runs exactly the `file` toolset
# (read/write/patch/search), mirroring Claude's file tools; both keep terminal off. --yolo is not mapped.
_PERMISSION_TOOLSETS = {READ_ONLY: "search,vision,todo,session_search", EDIT: "file"}
# A session id is a hex string: "local-<hex>" without the CLI and "<n>.<hex>" under a gateway, or an
# operator-named session. Only the shape that would be re-readable on the command line counts.
_UNKNOWN_SESSION = re.compile(r"No session found matching|session not found", re.IGNORECASE)


def _n(d: dict, key: str) -> int:
    v = d.get(key)
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def usage_of(result: dict) -> dict[str, int | float]:
    """The result envelope counts this invocation: `tokens` already excludes cache reads."""
    tokens = result.get("tokens") if isinstance(result.get("tokens"), dict) else {}
    prompt = _n(tokens, "input") + _n(tokens, "cache_read") + _n(tokens, "cache_write")
    output = _n(tokens, "output")
    return {"prompt_tokens": prompt, "completion_tokens": output, "cache_read_tokens": _n(tokens, "cache_read"),
            "cache_write_tokens": _n(tokens, "cache_write"), "reasoning_tokens": 0,
            "total_tokens": prompt + output, "model_calls": 1, "cost_usd": 0.0}


class HermesStream(StreamParser):
    """system/init (once the session id might still be empty), tool_use, tool_result, the full final
    text, then one result envelope. Subagent activity is not in the stream; the session id comes with
    the result, which also carries the error on failure."""

    def __init__(self, session_id_re: re.Pattern[str]) -> None:
        self._session_id_re = session_id_re
        self.session_id: str | None = None
        self.result: dict | None = None
        self.texts: list[str] = []
        self._tool_names: dict[str, str] = {}

    def feed(self, event: dict) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            # model / session_id arrive empty on a CLI one-shot; their presence would win anyway.
            out.append(("init", {k: event[k] for k in ("model", "session_id")
                                 if isinstance(event.get(k), str) and event[k]}))
        elif kind == "tool_use":
            call_id, name = str(event.get("tool_call_id", "")), str(event.get("name", "tool"))
            self._tool_names[call_id] = name
            out.append(("tool_call", {"id": call_id, "name": name, "args": event.get("input") or {}}))
        elif kind == "tool_result":
            call_id = str(event.get("tool_call_id", ""))
            out.append(("tool_result", {"tool_call_id": call_id, "name": self._tool_names.get(call_id, "tool"),
                                        "status": "error" if event.get("is_error") else "success",
                                        "content": str(event.get("output") or "")}))
        elif kind == "text":
            text = str(event.get("text", ""))
            if text.strip():
                self.texts.append(text.strip())
                out.append(("text", text))
        elif kind == "result":
            self.result = event
            sid = event.get("session_id")
            if isinstance(sid, str) and sid and sid != self.session_id and self._session_id_re.match(sid):
                self.session_id = sid
                out.append(("session", sid))
        return out

    def usage_so_far(self) -> dict[str, int | float] | None:
        return usage_of(self.result) if self.result else None

    def finish(self, *, exit_code: int, stderr: str, resumed: bool, baseline: dict | None) -> TurnResult:
        result = self.result
        if result is None:
            if resumed and _UNKNOWN_SESSION.search(stderr):
                raise UnknownSession
            detail = stderr.strip()[-1000:]
            raise CliAgentError(f"error: hermes exited with code {exit_code} without a result"
                                + (f": {detail}" if detail else ""))
        error = str(result.get("error") or "")
        code = _n(result, "exit_code")
        if error or code or exit_code:
            blob = f"{error} {result.get('text') or ''} {stderr}"
            if resumed and _UNKNOWN_SESSION.search(blob):
                raise UnknownSession
            detail = (error or str(result.get("text") or "") or stderr.strip())[-1000:]
            raise CliAgentError(f"error: hermes run failed ({code or exit_code})" + (f": {detail}" if detail else ""),
                                usage=usage_of(result))
        text = str(result.get("text") or "")
        return TurnResult(text=text or (self.texts[-1] if self.texts else ""), usage=usage_of(result),
                          session_id=self.session_id)


class Hermes(CliAdapter):
    provider = "hermes"
    label = "Hermes"
    binary = "hermes"
    path_setting = "hermes_path"
    install_hint = "Run `hermes` once in a terminal and finish sign-in, then restart OpenBot."
    status_argv = ()  # `hermes auth status` wants a provider name; its exit code is no login check.
    login_hint = "Run `hermes` in a terminal and finish sign-in."
    session_id_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_:.:-]{2,127}$")

    def install_dirs(self, *, home: str, env: Mapping[str, str], win: bool) -> list[str]:
        p = ntpath if win else posixpath
        if not win:
            return [p.join(home, ".local", "bin", "hermes"), "/usr/local/bin/hermes", "/opt/homebrew/bin/hermes"]
        found = [p.join(home, ".hermes", "bin", "hermes.exe"), p.join(home, ".local", "bin", "hermes.exe")]
        if env.get("APPDATA"):
            found.append(p.join(env["APPDATA"], "npm", "hermes.cmd"))
        return found

    def argv(self, executable: str, turn: Turn) -> list[str]:
        # The prompt is read from stdin; the system prompt has no separate slot and is prefixed there.
        argv = [executable, "chat", "--format", "stream-json", "--query-file", "-"]
        if turn.cwd:
            argv += ["--in", turn.cwd]  # a gateway services this turn with the same directory
        argv += ["-t", _PERMISSION_TOOLSETS[turn.permission]]
        if turn.model:
            argv += ["--model", turn.model]
        if turn.session_id:
            argv += ["--resume", turn.session_id]
        return argv

    def parser(self) -> HermesStream:
        return HermesStream(self.session_id_re)

    def combine(self, prompt: str, system_prompt: str) -> str:
        stripped = system_prompt.strip()
        return f"{stripped}\n\n{prompt}" if stripped else prompt
