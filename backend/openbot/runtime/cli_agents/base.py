"""What every coding agent CLI has in common: finding the executable, the environment it gets, the
process tree, reading its JSON event stream, and resuming a session. An adapter (claude_code.py) only
supplies the command line, the event format and how the CLI reports its login.

OpenBot never reads a CLI's credential files or keychain entries. It starts the installed executable,
which uses whatever login the user set up for it, and learns the login state only by asking the CLI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ntpath
import os
import posixpath
import re
import signal
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import AliasChoices

from openbot.config import Settings

log = logging.getLogger(__name__)

# What a CLI bot may do, in OpenBot's terms; each adapter maps the two onto its CLI's own modes.
# There is deliberately no level that turns the CLI's permission checks off.
READ_ONLY = "read-only"
EDIT = "edit"
PERMISSIONS = (READ_ONLY, EDIT)

KILL_GRACE = 5.0                 # seconds between SIGTERM (the CLI stops its own children) and SIGKILL
STREAM_LIMIT = 32 * 1024 * 1024  # one event line can carry a whole file read
STDERR_TAIL = 4000
PIPE_GRACE = 2.0                 # how long output may still arrive once the CLI itself has exited
EXIT_POLL = 0.25                 # how often a silent CLI is checked for having exited
STATUS_TIMEOUT = 15.0
VERSION_TIMEOUT = 30.0
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,119}$")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
# The CLI inherits the server environment minus everything OpenBot reads its own settings from (the
# backend loads .env into os.environ): SECRET_KEY, OPENBOT_API_KEY, provider and Telegram keys and so on.
# That includes a provider key the CLI would accept as its own login, such as ANTHROPIC_API_KEY: a key
# set up for OpenBot's provider must not quietly switch a CLI bot from the user's subscription to API billing.
_EXTRA_PRIVATE_ENV = ("LANGSMITH_API_KEY",)
# That list is derived from the Settings field names, so a future field with a generic name (path, home,
# user ...) would take the matching variable away and the CLI would find neither git nor its own config.
# What a process needs to run always passes.
_SYSTEM_ENV = ("PATH", "PATHEXT", "HOME", "USER", "USERNAME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
               "TEMP", "TMP", "TMPDIR", "SYSTEMROOT", "WINDIR", "COMSPEC", "SHELL", "LANG", "LC_ALL")


class CliAgentError(Exception):
    """A CLI run failed for a reason the user can act on; str() is the whole message. `usage` is what
    the CLI reported before failing, so a failed run still counts what it spent."""

    def __init__(self, message: str, usage: dict[str, int | float] | None = None,
                 totals: dict | None = None) -> None:
        super().__init__(message)
        self.usage, self.totals = usage, totals


class UnknownSession(Exception):
    """The stored session no longer exists (the CLI's transcripts were cleared, or another machine)."""


@dataclass(frozen=True)
class Turn:
    """One invocation. The thread messages go to stdin and the system prompt to a file only this user
    can read, never onto the command line."""

    system_prompt_file: str
    session_id: str | None
    model: str
    permission: str


@dataclass
class TurnResult:
    text: str
    usage: dict[str, int | float]
    session_id: str | None
    # What the CLI has counted for the whole session so far, if it reports that instead of one
    # invocation. Stored with the session and handed back as `baseline` on the next turn.
    totals: dict | None = None


class StreamParser(ABC):
    """Turns one CLI's events into run-level actions: ("session", id), ("init", {...}), ("delta", text),
    ("text", text), ("tool_call", {id, name, args}) and ("tool_result", {tool_call_id, name, status,
    content}). Pure, so tests feed it recorded lines."""

    session_id: str | None = None

    @abstractmethod
    def feed(self, event: dict) -> list[tuple[str, Any]]: ...

    @abstractmethod
    def finish(self, *, exit_code: int, stderr: str, resumed: bool, baseline: dict | None) -> TurnResult:
        """The turn's outcome once the process has exited. `baseline` is the resumed session's
        `totals` from its previous turn. Raises CliAgentError for a failed run, and UnknownSession
        when a resumed session is gone."""

    def usage_so_far(self) -> dict[str, int | float] | None:
        """Usage already reported when the run is stopped early (a timeout)."""
        return None


class CliAdapter(ABC):
    provider: str                       # the bot provider value, e.g. "claude-code"
    label: str                          # how messages name the CLI, e.g. "Claude Code"
    binary: str                         # the executable's name without extension
    path_setting: str                   # the Settings field that names the executable explicitly
    install_hint: str
    min_version: tuple[int, int, int] = (0, 0, 0)
    update_hint: str = ""
    version_argv: tuple[str, ...] = ("--version",)
    # The CLI's own "am I logged in" command; its exit code is the answer (0 means yes).
    status_argv: tuple[str, ...] = ()
    login_hint: str = ""
    session_id_re: re.Pattern[str] = re.compile(r"^[0-9a-fA-F-]{8,64}$")

    def install_dirs(self, *, home: str, env: Mapping[str, str], win: bool) -> list[str]:
        """Where the CLI's installers put it, beyond PATH: full paths to the executable."""
        return []

    @abstractmethod
    def argv(self, executable: str, turn: Turn) -> list[str]: ...

    @abstractmethod
    def parser(self) -> StreamParser: ...

    @property
    def not_found(self) -> str:
        return (f"error: {self.label} CLI ({self.binary}) not found. {self.install_hint} "
                f"Or set {self.path_setting.upper()} to the executable.")


# --- finding the executable -----------------------------------------------------------------------

def candidates(adapter: CliAdapter, *, platform: str = sys.platform, env: Mapping[str, str] = os.environ,
               home: str | None = None) -> list[str]:
    """Every place the CLI may live, in lookup order: PATH first, then where its installers put it.
    A GUI-launched app gets a minimal PATH, the same reason the desktop launcher searches for uv."""
    win = platform == "win32"
    p = ntpath if win else posixpath
    exts = [e.lower() for e in (env.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(";") if e] if win else [""]
    dirs = [d for d in (env.get("PATH") or env.get("Path") or "").split(";" if win else ":") if d]
    found = [p.join(d, adapter.binary + ext) for d in dirs for ext in exts]
    return found + adapter.install_dirs(home=home or str(Path.home()), env=env, win=win)


def _runnable(path: str) -> bool:
    return os.path.isfile(path) and (sys.platform == "win32" or os.access(path, os.X_OK))


def find_executable(adapter: CliAdapter, settings: Settings, *, paths: list[str] | None = None) -> str | None:
    """The configured path when set (and only that), else the first runnable candidate."""
    configured = getattr(settings, adapter.path_setting, None)
    if configured:
        path = str(Path(configured).expanduser())
        return path if _runnable(path) else None
    return next((c for c in (paths if paths is not None else candidates(adapter)) if _runnable(c)), None)


# --- the environment ------------------------------------------------------------------------------

def _openbot_env_names() -> set[str]:
    """Every variable OpenBot reads its own settings from: field names and their aliases."""
    names = {n.upper() for n in Settings.model_fields} | set(_EXTRA_PRIVATE_ENV)
    for f in Settings.model_fields.values():
        alias = f.validation_alias
        if isinstance(alias, str):
            names.add(alias.upper())
        elif isinstance(alias, AliasChoices):
            names.update(a.upper() for a in alias.choices if isinstance(a, str))
    return names


def child_env(env: Mapping[str, str] = os.environ) -> dict[str, str]:
    private = _openbot_env_names() - set(_SYSTEM_ENV)
    return {k: v for k, v in env.items() if k.upper() not in private}


# --- settings -------------------------------------------------------------------------------------

def settings_error(adapter: CliAdapter, model: str, model_settings: dict | None) -> str | None:
    """Why this bot's CLI settings are unusable, or None. Checked on save and again before each run:
    the model ends up on a command line."""
    ms = model_settings or {}
    if model and not _MODEL.match(model):
        return f"invalid {adapter.label} model {model!r}"
    if ms.get("permission", READ_ONLY) not in PERMISSIONS:
        return f"permission must be one of {', '.join(PERMISSIONS)}"
    timeout = ms.get("timeout_seconds")
    if timeout is not None and (not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1):
        return "timeout_seconds must be a positive whole number"
    return None


# --- the prompt -----------------------------------------------------------------------------------

def _content(m: BaseMessage) -> str:
    return m.content if isinstance(m.content, str) else str(m.content)


def render_messages(messages: list[BaseMessage], bot_name: str) -> str:
    """The thread as plain text: build_history already renders others as "[name] (new): text"."""
    return "\n\n".join(f"[{bot_name} (you)]: {_content(m)}" if isinstance(m, AIMessage) else _content(m)
                       for m in messages)


def since_last_reply(messages: list[BaseMessage]) -> list[BaseMessage]:
    """What a resumed session has not seen yet: everything after the bot's own latest reply."""
    last = max((i for i, m in enumerate(messages) if isinstance(m, AIMessage)), default=-1)
    return messages[last + 1:]


# --- the process ----------------------------------------------------------------------------------

class ProcessTree:
    """The CLI and everything it starts, so a cancel or a timeout stops all of it: a process group on
    macOS and Linux, a job object on Windows (taskkill /T if Windows refuses one)."""

    def __init__(self, proc: asyncio.subprocess.Process, job=None) -> None:
        self.proc, self._job = proc, job

    @classmethod
    async def spawn(cls, argv: list[str], *, cwd: str, env: dict[str, str]) -> ProcessTree:
        group: dict[str, Any] = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
                                 else {"start_new_session": True})
        proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                    limit=STREAM_LIMIT, **group)
        job = None
        if sys.platform == "win32":
            from openbot.tools.builtin.windows_job import WindowsJob
            job = WindowsJob.attach(proc.pid)
        return cls(proc, job)

    async def stop(self) -> None:
        if sys.platform == "win32":
            if self._job is not None:
                self._job.terminate()
            elif self.proc.returncode is None:
                killer = await asyncio.create_subprocess_exec("taskkill", "/pid", str(self.proc.pid), "/T", "/F",
                                                              stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            await self.proc.wait()
            return
        # start_new_session made the CLI a group leader, so its pid is the group id even after it exits.
        self._signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(self.proc.wait(), KILL_GRACE)
        except TimeoutError:
            pass
        self._signal(signal.SIGKILL)
        await _exit_code(self.proc)    # not wait(): that also waits for the pipes (see _next_line)

    def _signal(self, sig: int) -> None:
        try:
            os.killpg(self.proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def close(self) -> None:
        if self._job is not None:
            self._job.close()
            self._job = None


async def _answer(argv: list[str], *, cwd: str, env: dict[str, str], timeout: float) -> tuple[int, str] | None:
    """Exit code and stdout of a short CLI command, or None if it did not answer in time."""
    tree = await ProcessTree.spawn(argv, cwd=cwd, env=env)
    try:
        out, _err = await asyncio.wait_for(tree.proc.communicate(), timeout)
    except TimeoutError:
        await tree.stop()
        return None
    except BaseException:
        await tree.stop()
        raise
    finally:
        tree.close()
    return tree.proc.returncode, out.decode("utf-8", errors="replace")


async def login_status(adapter: CliAdapter, executable: str, env: dict[str, str]) -> bool | None:
    """Whether the CLI says it is logged in, from the exit code of its own status command. None when
    it has no such command or did not answer. OpenBot never opens a file to find this out."""
    if not adapter.status_argv:
        return None
    try:
        answer = await _answer([executable, *adapter.status_argv], cwd=str(Path.home()), env=env, timeout=STATUS_TIMEOUT)
    except OSError:
        return None
    return None if answer is None else answer[0] == 0


# (path, mtime) -> version, so the version command runs once per install and again after an update.
# Only touched from the event loop.
_versions: dict[tuple[str, float], tuple[int, int, int]] = {}


async def check_version(adapter: CliAdapter, executable: str, env: dict[str, str]) -> None:
    if adapter.min_version == (0, 0, 0):
        return
    try:
        key = (executable, os.path.getmtime(executable))
    except OSError:
        key = (executable, 0.0)
    if key not in _versions:
        command = f"`{adapter.binary} {' '.join(adapter.version_argv)}`"
        answer = await _answer([executable, *adapter.version_argv], cwd=str(Path(executable).parent), env=env,
                               timeout=VERSION_TIMEOUT)
        if answer is None:
            raise CliAgentError(f"error: {command} did not answer within {int(VERSION_TIMEOUT)}s")
        m = _VERSION.search(answer[1])
        if m is None:
            raise CliAgentError(f"error: could not read the {adapter.label} version from {command}: {answer[1].strip()[:200]!r}")
        _versions[key] = (int(m[1]), int(m[2]), int(m[3]))
    if _versions[key] < adapter.min_version:
        raise CliAgentError(f"error: {adapter.label} {'.'.join(map(str, _versions[key]))} is too old; OpenBot needs "
                            f"{'.'.join(map(str, adapter.min_version))} or later. {adapter.update_hint}".rstrip())


async def _tail(stream: asyncio.StreamReader | None) -> str:
    buf = ""
    if stream is None:
        return buf
    while chunk := await stream.read(65536):
        buf = (buf + chunk.decode(errors="replace"))[-STDERR_TAIL:]
    return buf


async def _next_line(proc: asyncio.subprocess.Process) -> bytes | None:
    """The CLI's next output line, b"" at the end of its output. None when the CLI has exited and the
    pipe is only still open because something it started is running and inherited it: reading on would
    wait for that process instead of the turn. The exit is read off `returncode`, since on POSIX
    `proc.wait()` itself only returns once the pipes are closed."""
    read = asyncio.ensure_future(proc.stdout.readline())
    try:
        while True:
            done, _ = await asyncio.wait({read}, timeout=EXIT_POLL)
            if done:
                return read.result()
            if proc.returncode is not None:
                return await asyncio.wait_for(read, PIPE_GRACE)
    except TimeoutError:
        return None
    finally:
        if not read.done():
            read.cancel()


async def _exit_code(proc: asyncio.subprocess.Process) -> int:
    while proc.returncode is None:
        await asyncio.sleep(0.05)
    return proc.returncode


OnEvent = Callable[[str, Any], Awaitable[None]]


async def _turn(adapter: CliAdapter, executable: str, *, cwd: str, env: dict[str, str], system_prompt: str,
                prompt: str, session_id: str | None, model: str, permission: str, timeout: float,
                on_event: OnEvent, baseline: dict | None = None) -> TurnResult:
    fd, prompt_file = tempfile.mkstemp(prefix="openbot-system-", suffix=".md")   # 0600
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(system_prompt)
    argv = adapter.argv(executable, Turn(system_prompt_file=prompt_file, session_id=session_id, model=model,
                                         permission=permission))
    parser = adapter.parser()
    stderr_task: asyncio.Task | None = None
    try:
        tree = await ProcessTree.spawn(argv, cwd=cwd, env=env)
        stderr_task = asyncio.create_task(_tail(tree.proc.stderr))
        left_behind = False
        try:
            async with asyncio.timeout(timeout):
                try:
                    tree.proc.stdin.write(prompt.encode("utf-8"))
                    await tree.proc.stdin.drain()
                    tree.proc.stdin.close()
                except (BrokenPipeError, ConnectionResetError):
                    pass    # it exited before reading; stderr and the exit code say why
                while raw := await _next_line(tree.proc):
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        log.debug("%s: non-JSON output line: %s", adapter.binary, line[:200])
                        continue
                    if isinstance(event, dict):
                        for kind, payload in parser.feed(event):
                            await on_event(kind, payload)
                left_behind = raw is None
                code = await _exit_code(tree.proc)
            try:
                stderr = await asyncio.wait_for(asyncio.shield(stderr_task), PIPE_GRACE)
            except TimeoutError:
                left_behind, stderr = True, ""
            if left_behind:
                # The turn is over; a process it started must not outlive it, or keep the pipes open.
                await tree.stop()
                try:
                    stderr = await asyncio.wait_for(stderr_task, PIPE_GRACE)
                except TimeoutError:
                    pass
        except TimeoutError:
            await tree.stop()
            raise CliAgentError(f"error: {adapter.binary} did not finish within {int(timeout)}s and was stopped",
                                usage=parser.usage_so_far()) from None
        except BaseException:
            # Cancelled run, or a failure while handling an event: never leave the CLI running.
            await tree.stop()
            raise
        finally:
            tree.close()
    finally:
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
        try:
            os.unlink(prompt_file)
        except OSError:
            pass
    return parser.finish(exit_code=code, stderr=stderr, resumed=session_id is not None, baseline=baseline)


async def run_turn(adapter: CliAdapter, executable: str, *, cwd: str, env: dict[str, str], system_prompt: str,
                   full_prompt: str, resume: tuple[str, str, dict | None] | None, model: str,
                   model_settings: dict | None, timeout: float, on_event: OnEvent) -> TurnResult:
    """One bot turn. `resume` is (session id, the messages that session has not seen, the session's
    totals so far); if the CLI no longer knows that session, the turn starts over in a new one with the
    whole visible thread."""
    error = settings_error(adapter, model, model_settings)
    if error:
        raise CliAgentError(f"error: {error}")
    await check_version(adapter, executable, env)
    kwargs = {"cwd": cwd, "env": env, "system_prompt": system_prompt, "model": model, "timeout": timeout,
              "permission": (model_settings or {}).get("permission", READ_ONLY), "on_event": on_event}
    if resume is not None and adapter.session_id_re.match(resume[0]):
        try:
            return await _turn(adapter, executable, prompt=resume[1], session_id=resume[0], baseline=resume[2], **kwargs)
        except UnknownSession:
            log.info("%s session %s is gone; starting a new one", adapter.binary, resume[0])
    return await _turn(adapter, executable, prompt=full_prompt, session_id=None, **kwargs)
