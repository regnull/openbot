import asyncio
import os
from pathlib import Path

import pytest
from langchain.tools import ToolRuntime

from openbot.tools.builtin import SELECTABLE_TOOLS
from openbot.tools.builtin.files import list_files, read_file, write_file
from openbot.tools.builtin.shell import run_shell
from openbot.tools.builtin.workspace import resolve_in_workspace
from openbot.tools.context import RunContext


def ctx(root: Path) -> RunContext:
    root.mkdir(parents=True, exist_ok=True)
    return RunContext("b", "bot", "Bot", "t", "r", root.resolve(), None)


def rt(root: Path) -> ToolRuntime:
    return ToolRuntime(context=ctx(root), store=None, state={}, tool_call_id="c", config={}, stream_writer=lambda *_: None)


def test_resolve_in_workspace(tmp_path):
    root = tmp_path.resolve()
    assert resolve_in_workspace(root, None) == root
    assert resolve_in_workspace(root, "a/b") == root / "a" / "b"
    with pytest.raises(ValueError):
        resolve_in_workspace(root, "../x")
    with pytest.raises(ValueError):
        resolve_in_workspace(root, "/etc/passwd")


async def test_files_roundtrip(tmp_path):
    r = rt(tmp_path)
    assert "wrote" in await write_file.ainvoke({"path": "a/hello.txt", "content": "hi", "runtime": r})
    assert await read_file.ainvoke({"path": "a/hello.txt", "runtime": r}) == "hi"
    out = await list_files.ainvoke({"path": ".", "depth": 2, "runtime": r})
    assert "a/hello.txt" in out
    out = await read_file.ainvoke({"path": "../secret", "runtime": r})
    assert out.startswith("error:")


async def test_run_shell(tmp_path):
    r = rt(tmp_path)
    out = await run_shell.ainvoke({"command": "echo hello; echo err 1>&2; exit 3", "runtime": r})
    assert "exit code: 3" in out and "hello" in out and "err" in out
    out = await run_shell.ainvoke({"command": "sleep 5", "timeout": 1, "runtime": r})
    assert "timed out" in out
    out = await run_shell.ainvoke({"command": "pwd", "cwd": "../", "runtime": r})
    assert out.startswith("error:")


async def test_run_shell_kills_process_group_on_timeout(tmp_path):
    r = rt(tmp_path)
    start = asyncio.get_event_loop().time()
    out = await run_shell.ainvoke({
        "command": "sleep 5 & echo $! > child.pid; wait",
        "timeout": 1,
        "runtime": r,
    })
    elapsed = asyncio.get_event_loop().time() - start
    assert "timed out" in out
    # If only the top-level bash pid were killed, the backgrounded `sleep 5` would
    # keep the stdout/stderr pipes open and `proc.wait()` would block for the full
    # 5s until it exits on its own. Killing the whole process group must make the
    # tool return promptly instead.
    assert elapsed < 2, f"run_shell took {elapsed:.2f}s - orphaned child was not killed promptly"
    pid_file = tmp_path / "child.pid"
    assert pid_file.exists()
    child_pid = int(pid_file.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_selectable_names():
    assert [t.name for t in SELECTABLE_TOOLS] == [
        "run_shell", "read_file", "write_file", "list_files", "http_request", "fetch_url"]
