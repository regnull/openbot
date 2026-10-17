import asyncio
import os
import sys
from pathlib import Path

import pytest
from langchain.tools import ToolRuntime

from openbot.tools.builtin import SELECTABLE_TOOLS
from openbot.tools.builtin.files import edit_file, list_files, read_file, write_file
from openbot.tools.builtin.shell import run_shell
from openbot.tools.builtin.workspace import (
    browse_workspace_directory,
    resolve_in_workspace,
    thread_workspace_root,
    validate_workspace_directory,
)
from openbot.tools.context import RunContext


def ctx(root: Path) -> RunContext:
    root.mkdir(parents=True, exist_ok=True)
    return RunContext("b", "bot", "Bot", "t", "r", root.resolve(), None)


def rt(root: Path) -> ToolRuntime:
    return ToolRuntime(
        context=ctx(root),
        store=None,
        state={},
        tool_call_id="c",
        config={},
        stream_writer=lambda *_: None,
    )


# The pid of the last background job. Under Git Bash on Windows $! is an MSYS pid, not a Windows one.
LAST_PID = "$(cat /proc/$!/winpid)" if sys.platform == "win32" else "$!"


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) would terminate the process on Windows instead of probing it.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259                                     # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_resolve_in_workspace(tmp_path):
    root = tmp_path.resolve()
    assert resolve_in_workspace(root, None) == root
    assert resolve_in_workspace(root, "a/b") == root / "a" / "b"
    with pytest.raises(ValueError):
        resolve_in_workspace(root, "../x")


def test_validate_workspace_directory(tmp_path):
    root = tmp_path.resolve()
    (root / "repo" / "src").mkdir(parents=True)
    (root / "repo" / "file.txt").write_text("hi")

    assert validate_workspace_directory(root, None) is None
    assert validate_workspace_directory(root, "") is None
    assert validate_workspace_directory(root, ".") is None
    assert validate_workspace_directory(root, "repo/../repo/src") == "repo/src"
    home = Path.home() / "work" / "core-web"
    if home.is_dir():
        assert (
            validate_workspace_directory(Path.home() / "work", "~/work/core-web")
            == "~/work/core-web"
        )

    outside = tmp_path / "outside"
    outside.mkdir()
    assert validate_workspace_directory(root, str(outside)) == outside.as_posix()

    for bad in ("../x", str(tmp_path / "missing"), "repo/missing", "repo/file.txt", "repo\nname"):
        with pytest.raises(ValueError):
            validate_workspace_directory(root, bad)


def test_browse_workspace_directory(tmp_path):
    root = tmp_path.resolve()
    (root / "repo" / "src").mkdir(parents=True)
    (root / "repo" / "docs").mkdir()
    (root / "repo" / ".git").mkdir()
    (root / "repo" / "README.md").write_text("hi")
    (root / "Zed").mkdir()

    here, parent, entries = browse_workspace_directory(root, None)
    assert (here, parent) == (".", None)
    assert entries == [("repo", "repo"), ("Zed", "Zed")]  # case-insensitive order, files skipped

    here, parent, entries = browse_workspace_directory(root, "repo")
    assert (here, parent) == ("repo", ".")
    assert entries == [("docs", "repo/docs"), ("src", "repo/src")]  # hidden .git skipped

    here, parent, entries = browse_workspace_directory(root, "repo/src")
    assert (here, parent, entries) == ("repo/src", "repo", [])

    here, parent, _ = browse_workspace_directory(root, "~")
    assert (here, parent) == ("~", None)
    if (Path.home() / "work").is_dir():
        here, parent, entries = browse_workspace_directory(root, "~/work")
        assert (here, parent) == ("~/work", "~")
        assert all(path.startswith("~/work/") for _, path in entries)

    for bad in ("../x", str(tmp_path / "missing"), "repo/missing", "repo/README.md", "~/.."):
        with pytest.raises(ValueError):
            browse_workspace_directory(root, bad)


async def test_files_roundtrip(tmp_path):
    r = rt(tmp_path)
    assert "wrote" in await write_file.ainvoke(
        {"path": "a/hello.txt", "content": "hi", "runtime": r}
    )
    assert await read_file.ainvoke({"path": "a/hello.txt", "runtime": r}) == "1: hi"
    out = await list_files.ainvoke({"path": ".", "depth": 2, "runtime": r})
    assert "a/hello.txt" in out
    out = await read_file.ainvoke({"path": "../secret", "runtime": r})
    assert out.startswith("error:")


@pytest.mark.parametrize(
    ("old", "expected"),
    [
        ("alpha\nbeta", "ALPHA\nBETA"),
        (" alpha\n beta", "ALPHA\nBETA"),
        ("alpha  beta", "ALPHA\nBETA"),
        ("    alpha\n    beta", "ALPHA\nBETA"),
        (r"alpha\nbeta", "ALPHA\nBETA"),
    ],
)
async def test_edit_file_matchers(tmp_path, old, expected):
    r = rt(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha\nbeta\n")
    out = await edit_file.ainvoke(
        {"path": "notes.txt", "old_string": old, "new_string": expected, "runtime": r}
    )
    assert out.startswith("edited notes.txt")
    assert (tmp_path / "notes.txt").read_text() == expected + "\n"


async def test_edit_file_rejects_ambiguous_anchor_matches(tmp_path):
    r = rt(tmp_path)
    original = "START\nKEEP\nA\nEND\nSTART\nKEEP\nB\nEND\n"
    (tmp_path / "notes.txt").write_text(original)
    out = await edit_file.ainvoke(
        {
            "path": "notes.txt",
            "old_string": "START\nKEEP\nOLD\nEND",
            "new_string": "START\nKEEP\nNEW\nEND",
            "runtime": r,
        }
    )
    assert "matched 2 locations" in out
    assert (tmp_path / "notes.txt").read_text() == original


async def test_edit_file_rejects_ambiguous_and_oversized_matches(tmp_path):
    r = rt(tmp_path)
    (tmp_path / "notes.txt").write_text("same\\nsame\\n")
    out = await edit_file.ainvoke(
        {"path": "notes.txt", "old_string": "same", "new_string": "new", "runtime": r}
    )
    assert "matched 2 locations" in out
    out = await edit_file.ainvoke(
        {
            "path": "notes.txt",
            "old_string": "same",
            "new_string": "new",
            "replace_all": True,
            "runtime": r,
        }
    )
    assert "2 replacements" in out
    (tmp_path / "large.txt").write_text("x" * 1000)
    out = await edit_file.ainvoke(
        {"path": "large.txt", "old_string": "x", "new_string": "y", "runtime": r}
    )
    assert "matched 1000 locations" in out


@pytest.mark.parametrize(
    ("content", "old"),
    [("aaa", "aa"), ("alpha  beta\nalpha   beta", "alpha beta")],
)
async def test_edit_file_rejects_overlapping_or_normalized_ambiguous_matches(
    tmp_path, content, old
):
    r = rt(tmp_path)
    (tmp_path / "notes.txt").write_text(content)
    out = await edit_file.ainvoke(
        {"path": "notes.txt", "old_string": old, "new_string": "changed", "runtime": r}
    )
    assert "matched 2 locations" in out
    assert (tmp_path / "notes.txt").read_text() == content


async def test_edit_file_rejects_overlapping_replace_all_matches(tmp_path):
    r = rt(tmp_path)
    content = "aaa"
    (tmp_path / "notes.txt").write_text(content)
    out = await edit_file.ainvoke(
        {
            "path": "notes.txt",
            "old_string": "aa",
            "new_string": "changed",
            "runtime": r,
            "replace_all": True,
        }
    )
    assert "replace_all cannot apply overlapping matches" in out
    assert (tmp_path / "notes.txt").read_text() == content


async def test_edit_file_preserves_crlf_and_bom(tmp_path):
    r = rt(tmp_path)
    (tmp_path / "windows.txt").write_bytes(b"\xef\xbb\xbffirst\r\nsecond\r\n")
    out = await edit_file.ainvoke(
        {
            "path": "windows.txt",
            "old_string": "first\nsecond",
            "new_string": "changed",
            "runtime": r,
        }
    )
    assert out.startswith("edited windows.txt")
    assert (tmp_path / "windows.txt").read_bytes() == b"\xef\xbb\xbfchanged\r\n"


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
    out = await run_shell.ainvoke(
        {
        "command": f"sleep 5 & echo {LAST_PID} > child.pid; wait",
        "timeout": 1,
        "runtime": r,
        }
    )
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
    assert not alive(child_pid)


@pytest.mark.skipif(sys.platform == "win32", reason="SHELL_USER is POSIX only")
async def test_run_shell_as_shell_user_runs_through_setpriv_with_a_minimal_env(
    tmp_path, monkeypatch
):
    # Switching users needs root and Linux's setpriv, so record what run_shell asks for and run the
    # command itself without the prefix. The real switch is covered by test_docker_live.py.
    import getpass
    import pwd

    import openbot.tools.builtin.shell as shell_mod

    monkeypatch.setenv("OPENAI_API_KEY", "sk-sentinel")
    monkeypatch.setattr(shell_mod.os, "geteuid", lambda: 0)
    seen = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        seen["argv"], seen["env"] = list(args), kwargs.get("env")
        command = args[args.index("--") + 1:]
        return await real(*command, **{k: v for k, v in kwargs.items() if k != "env"})

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    r = rt(tmp_path)
    name = getpass.getuser()
    r.context.shell_user = name
    out = await run_shell.ainvoke({"command": "echo ok", "runtime": r})

    entry = pwd.getpwnam(name)
    assert "ok" in out
    assert seen["argv"][:6] == [
        "setpriv",
        f"--reuid={entry.pw_uid}",
        f"--regid={entry.pw_gid}",
        "--init-groups",
        "--no-new-privs",
        "--",
    ]
    assert seen["argv"][6:8] == ["bash", "-lc"]
    assert set(seen["env"]) == {"PATH", "HOME", "USER", "LOGNAME", "LANG"}
    assert "OPENAI_API_KEY" not in seen["env"]


async def test_run_shell_without_shell_user_is_unchanged(tmp_path, monkeypatch):
    seen = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        seen["argv"], seen["env"] = list(args), kwargs.get("env")
        return await real(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    await run_shell.ainvoke({"command": "true", "runtime": rt(tmp_path)})
    assert seen["argv"][0] != "setpriv" and seen["env"] is None


@pytest.mark.skipif(sys.platform == "win32", reason="SHELL_USER is POSIX only")
async def test_run_shell_shell_user_fails_closed(tmp_path, monkeypatch):
    import getpass

    import openbot.tools.builtin.shell as shell_mod

    r = rt(tmp_path)
    r.context.shell_user = getpass.getuser()
    monkeypatch.setattr(shell_mod.os, "geteuid", lambda: 1000)
    out = await run_shell.ainvoke({"command": "touch ran", "runtime": r})
    assert out.startswith("error:") and "has to run as root" in out

    monkeypatch.setattr(shell_mod.os, "geteuid", lambda: 0)
    r.context.shell_user = "no-such-user-openbot"
    out = await run_shell.ainvoke({"command": "touch ran", "runtime": r})
    assert out.startswith("error:") and "does not exist" in out

    async def no_setpriv(*args, **kwargs):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_setpriv)
    r.context.shell_user = getpass.getuser()
    out = await run_shell.ainvoke({"command": "touch ran", "runtime": r})
    assert out.startswith("error:") and "setpriv" in out
    assert not (tmp_path / "ran").exists()


async def test_run_shell_kills_process_group_on_cancellation(tmp_path):
    # Cancelling a run cancels the tool coroutine. Without a killpg on CancelledError the shell and
    # everything it spawned keep running after the run is gone -- an orphaned build or `sleep` that
    # nothing will ever reap.
    r = rt(tmp_path)
    task = asyncio.create_task(
        run_shell.ainvoke(
            {
        "command": f"sleep 5 & echo {LAST_PID} > child.pid; wait",
        "timeout": 30,
        "runtime": r,
            }
        )
    )
    pid_file = tmp_path / "child.pid"
    for _ in range(100):                      # wait for bash to actually spawn the child
        await asyncio.sleep(0.01)
        if pid_file.exists() and pid_file.read_text().strip():
            break
    child_pid = int(pid_file.read_text().strip())
    assert alive(child_pid)                   # alive before the cancel
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(100):
        if not alive(child_pid):
            break
        await asyncio.sleep(0.01)
    assert not alive(child_pid)


def test_selectable_names():
    assert [t.name for t in SELECTABLE_TOOLS] == [
        "run_shell",
        "read_file",
        "write_file",
        "edit_file",
        "patch_file",
        "list_files",
        "search_code",
        "find_files",
        "http_request",
        "fetch_url",
        "create_bot",
        "read_bot_description",
        "read_bot_instructions",
        "update_bot_description",
        "update_bot_instructions",
        "todo_write",
    ]


async def test_search_code_returns_matching_lines_with_paths_and_skips_junk_dirs(tmp_path):
    """Exploration used to be `cat` after `cat`: ten model calls of whole-file dumps before the first
    edit. A search that returns only matching lines, with their location, replaces most of them."""
    from openbot.tools.builtin.search import search_code

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        "import os\n\ndef alpha():\n    return os.getcwd()\n\nclass Beta:\n    pass\n"
    )
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
    out = await search_code.ainvoke(
        {"pattern": "needle", "max_results": 20, "runtime": rt(tmp_path)}
    )
    assert out.count("many.txt:") == 20 and "more matches" in out


def test_search_code_is_selectable():
    assert "search_code" in [t.name for t in SELECTABLE_TOOLS]


def test_home_relative_core_web_and_rejects_traversal(tmp_path, monkeypatch):
    home = tmp_path / "home"
    target = home / "work" / "core-web"
    target.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))                     # what expanduser reads on Windows
    assert (
        validate_workspace_directory(tmp_path / "workspace", "~/work/core-web") == "~/work/core-web"
    )
    with pytest.raises(ValueError, match="cannot contain"):
        validate_workspace_directory(tmp_path / "workspace", "~/../outside")
    assert thread_workspace_root(tmp_path / "workspace", "~/work/core-web") == target


async def test_workspace_tools_keep_out_of_the_openbot_state_dir(tmp_path):
    """In root-directory mode the live SQLite files live at <workspace>/.openbot. Opening them from
    the backend process (read_file, search_code's walk) drops the process's POSIX locks on the WAL
    index, after which a `sqlite3` CLI the bot runs sees itself as the only connection, checkpoints
    under the backend and every open connection reports "database disk image is malformed"."""
    from openbot.tools.builtin.search import search_code

    state = tmp_path / ".openbot"
    state.mkdir()
    (state / "openbot.db-shm").write_text("needle in the wal index\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle = 1\n")
    r = rt(tmp_path)
    out = await search_code.ainvoke({"pattern": "needle", "runtime": r})
    assert "src/a.py:1: needle = 1" in out and ".openbot" not in out
    assert (await read_file.ainvoke({"path": ".openbot/openbot.db-shm", "runtime": r})).startswith(
        "error:"
    )
    assert (
        await write_file.ainvoke({"path": ".openbot/x", "content": "y", "runtime": r})
    ).startswith("error:")
    assert ".openbot" not in await list_files.ainvoke({"runtime": r, "depth": 2})
    assert "openbot.db-shm" not in await list_files.ainvoke({"runtime": r, "path": ".openbot"})
    with pytest.raises(ValueError, match="OpenBot state directory"):
        resolve_in_workspace(tmp_path.resolve(), ".openbot/openbot.db")
    with pytest.raises(ValueError, match="OpenBot state directory"):
        resolve_in_workspace(tmp_path.resolve(), str(state / "openbot.db"))


async def test_find_files_matching_by_glob(tmp_path):
    """find_files returns files matching a glob, sorted by mtime newest-first."""
    from openbot.tools.builtin.search import find_files

    (tmp_path / "src").mkdir()
    a = tmp_path / "src" / "a.py"
    a.write_text("line1\nline2\n")
    b = tmp_path / "src" / "b.ts"
    b.write_text("hello\n")
    c = tmp_path / "src" / "c.py"
    c.write_text("x" * 100 + "\n")

    r = rt(tmp_path)

    # All .py files
    out = await find_files.ainvoke({"glob_pattern": "*.py", "runtime": r, "path": "src"})
    assert "a.py:" in out and "c.py:" in out
    assert "b.ts" not in out

    # No matches
    out = await find_files.ainvoke({"glob_pattern": "*.rust", "runtime": r})
    assert out == "(no matches)"


async def test_find_files_sorted_by_mtime_newest_first(tmp_path):
    """Results are sorted by modification time, newest first."""
    from openbot.tools.builtin.search import find_files

    old = tmp_path / "old.txt"
    old.write_text("old\n")
    await asyncio.sleep(0.05)  # ensure distinct mtime

    new = tmp_path / "new.txt"
    new.write_text("new\n")

    r = rt(tmp_path)
    out = await find_files.ainvoke({"glob_pattern": "*.txt", "runtime": r})
    lines = out.strip().splitlines()
    assert len(lines) == 2
    # Newest first
    assert "new.txt" in lines[0]


async def test_find_files_skips_junk_dirs(tmp_path):
    """Binary files and files in junk directories are skipped."""
    from openbot.tools.builtin.search import find_files

    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("code\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "work.py").write_text("real code\n")
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02")

    r = rt(tmp_path)
    out = await find_files.ainvoke({"glob_pattern": "*", "runtime": r})
    assert "src/work.py" in out
    assert "node_modules" not in out
    assert ".git" not in out
    assert "binary.bin" not in out


async def test_find_files_caps_at_100_results(tmp_path):
    """At most 100 files are returned."""
    from openbot.tools.builtin.search import find_files

    for i in range(150):
        (tmp_path / f"f{i:04d}.txt").write_text(f"content {i}\n")

    r = rt(tmp_path)
    out = await find_files.ainvoke({"glob_pattern": "*.txt", "runtime": r})
    lines = out.strip().splitlines()
    assert len(lines) == 100


def test_find_files_is_selectable():
    assert "find_files" in [t.name for t in SELECTABLE_TOOLS]


async def test_search_code_uses_rg_when_available(tmp_path, monkeypatch):
    """When shutil.which('rg') finds rg, _search_code_rg is called."""
    from openbot.tools.builtin.search import search_code

    # Create a file the rg mock will "search"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle = 1\n")

    calls: list[list[str]] = []

    def fake_rg(*cmd_parts: str) -> str:
        calls.append(list(cmd_parts))
        # Simulate rg --json output
        return (
            '{"type":"begin","data":{"path":{"text":"src/a.py"}}}\n'
            '{"type":"match","data":{"path":{"text":"src/a.py"},"lines":{"text":"needle = 1\\n"},"line_number":1}}\n'
            '{"type":"end","data":{"path":{"text":"src/a.py"}}}\n'
            '{"type":"summary","data":{"stats":{"elapsed":{"secs":0,"nanos":0},"searches_with_match":1}}}\n'
        )

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/rg")
    # Replace subprocess.run with a fake that returns our canned output
    import subprocess

    def fake_run(cmd, **kwargs):
        # Return canned rg output
        class FakeResult:
            returncode = 0
            stdout = fake_rg(*cmd)
            stderr = ""
        return FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)

    r = rt(tmp_path)
    out = await search_code.ainvoke({"pattern": "needle", "runtime": r})
    assert "src/a.py:1: needle = 1" in out


@pytest.mark.skipif(sys.platform == "win32", reason="the fake rg is a POSIX shell script")
async def test_search_code_falls_back_when_rg_on_path_is_not_ripgrep(tmp_path, monkeypatch):
    """A pyenv shim named `rg` for a Python version that is not installed exits 1, rg's "no matches",
    with only an error on stderr. search_code took that as no matches for every pattern, so bots fell
    back to grep and sed through run_shell. Output without ripgrep's closing summary record means the
    search did not run, and the Python walk takes over."""
    from openbot.tools.builtin.search import search_code

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle = 1\n")
    shim = tmp_path / "bin" / "rg"
    shim.parent.mkdir()
    shim.write_text("#!/bin/sh\necho \"pyenv: version '3.13' is not installed\" >&2\nexit 1\n")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    out = await search_code.ainvoke({"pattern": "needle", "runtime": rt(tmp_path)})
    assert "src/a.py:1: needle = 1" in out


async def test_find_files_handles_root_level_skip_dir_names(tmp_path):
    """A file named .git is fine; only directories named .git are skipped."""
    from openbot.tools.builtin.search import find_files

    (tmp_path / ".git").write_text("not really a dir\n")          # file, not dir
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "work.py").write_text("real code\n")

    r = rt(tmp_path)
    out = await find_files.ainvoke({"glob_pattern": "*", "runtime": r})
    assert "src/work.py" in out
    # The file named ".git" should appear because it's a file, not a directory
    assert ".git" in out
