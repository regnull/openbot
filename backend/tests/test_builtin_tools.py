import asyncio
import os
from pathlib import Path

import pytest
from langchain.tools import ToolRuntime

from openbot.tools.builtin import SELECTABLE_TOOLS
from openbot.tools.builtin.files import list_files, read_file, write_file
from openbot.tools.builtin.shell import run_shell
from openbot.tools.builtin.workspace import resolve_in_workspace, validate_workspace_directory
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


def test_validate_workspace_directory(tmp_path):
    root = tmp_path.resolve()
    (root / "repo" / "src").mkdir(parents=True)
    (root / "repo" / "file.txt").write_text("hi")

    assert validate_workspace_directory(root, None) is None
    assert validate_workspace_directory(root, "") is None
    assert validate_workspace_directory(root, ".") is None
    assert validate_workspace_directory(root, "repo/../repo/src") == "repo/src"

    for bad in ("../x", "/tmp", "repo/missing", "repo/file.txt", "repo\nname"):
        with pytest.raises(ValueError):
            validate_workspace_directory(root, bad)


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


async def test_run_shell_kills_process_group_on_cancellation(tmp_path):
    # Cancelling a run cancels the tool coroutine. Without a killpg on CancelledError the shell and
    # everything it spawned keep running after the run is gone -- an orphaned build or `sleep` that
    # nothing will ever reap.
    r = rt(tmp_path)
    task = asyncio.create_task(run_shell.ainvoke({
        "command": "sleep 5 & echo $! > child.pid; wait",
        "timeout": 30,
        "runtime": r,
    }))
    pid_file = tmp_path / "child.pid"
    for _ in range(100):                      # wait for bash to actually spawn the child
        await asyncio.sleep(0.01)
        if pid_file.exists() and pid_file.read_text().strip():
            break
    child_pid = int(pid_file.read_text().strip())
    os.kill(child_pid, 0)                     # alive before the cancel
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(100):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.01)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_selectable_names():
    assert [t.name for t in SELECTABLE_TOOLS] == [
        "run_shell", "read_file", "write_file", "list_files", "search_code", "http_request", "fetch_url", "create_bot"]


async def test_search_code_returns_matching_lines_with_paths_and_skips_junk_dirs(tmp_path):
    """Exploration used to be `cat` after `cat`: ten model calls of whole-file dumps before the first
    edit. A search that returns only matching lines, with their location, replaces most of them."""
    from openbot.tools.builtin.search import search_code
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("import os\n\ndef alpha():\n    return os.getcwd()\n\nclass Beta:\n    pass\n")
    (tmp_path / "src" / "b.ts").write_text("export function alpha() {}\nconst beta = 1;\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("alpha alpha alpha\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("alpha\n")
    (tmp_path / "bin.dat").write_bytes(b"alpha\x00\x01\x02")
    r = rt(tmp_path)
    out = await search_code.ainvoke({"pattern": r"def alpha|function alpha", "runtime": r})
    assert "src/a.py:3: def alpha():" in out and "src/b.ts:1: export function alpha() {}" in out
    assert "node_modules" not in out and ".git" not in out and "bin.dat" not in out
    out = await search_code.ainvoke({"pattern": "alpha", "glob": "*.py", "runtime": r})
    assert "a.py" in out and "b.ts" not in out
    out = await search_code.ainvoke({"pattern": "class Beta", "context": 1, "runtime": r})
    assert "src/a.py:5-" in out or "src/a.py:5:" in out
    assert "    pass" in out                                  # one line of context after the match
    out = await search_code.ainvoke({"pattern": "nothing_here_zzz", "runtime": r})
    assert out == "(no matches)"
    out = await search_code.ainvoke({"pattern": "(", "runtime": r})
    assert out.startswith("error:")


async def test_search_code_caps_the_number_of_matches(tmp_path):
    from openbot.tools.builtin.search import search_code
    (tmp_path / "many.txt").write_text("\n".join(f"needle {i}" for i in range(500)))
    out = await search_code.ainvoke({"pattern": "needle", "max_results": 20, "runtime": rt(tmp_path)})
    assert out.count("many.txt:") == 20 and "more matches" in out


def test_search_code_is_selectable():
    assert "search_code" in [t.name for t in SELECTABLE_TOOLS]
