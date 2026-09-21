"""Tests for the ``patch_file`` tool.

Covers:
1. Unified-diff (``diff_input``) mode with the system ``patch`` command
2. Dry-run, backup, strip-level options
3. Error handling: empty input, invalid patches, missing diff_input
4. Edge cases: whitespace-only input, malformed diffs
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch as mock_patch

from langchain.tools import ToolRuntime

from openbot.tools.builtin.files import _apply_patch_command, patch_file
from openbot.tools.context import RunContext

# ── Helpers ─────────────────────────────────────────────────────────────────


def rt(root: Path) -> ToolRuntime:
    root.mkdir(parents=True, exist_ok=True)
    context = RunContext("b", "bot", "Bot", "t", "r", root.resolve(), None)
    return ToolRuntime(context=context, store=None, state={}, tool_call_id="c", config={}, stream_writer=lambda *_: None)


def _write_hello(tmp: Path, content: str = "Hello\nWorld\nGoodbye\n") -> Path:
    p = tmp / "hello.txt"
    p.write_text(content)
    return p


# ── Constants ───────────────────────────────────────────────────────────────

SIMPLE_DIFF = """\
--- a/hello.txt
+++ b/hello.txt
@@ -1,3 +1,3 @@
 Hello
-World
+Universe
 Goodbye
"""

# ── Tests for unified-diff (diff_input) mode ────────────────────────────────


async def test_patch_file_diff_input_applies_unified_diff(tmp_path):
    """Passing a valid unified diff via *diff_input* modifies the file."""
    target = _write_hello(tmp_path)
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "diff_input": SIMPLE_DIFF,
        "runtime": runtime,
    })
    assert "patching file" in result.lower() or "patch applied" in result.lower()
    assert target.read_text() == "Hello\nUniverse\nGoodbye\n"


async def test_patch_file_diff_input_dry_run_does_not_modify(tmp_path):
    """With *dry_run=True* the file must remain unchanged."""
    target = _write_hello(tmp_path)
    before = target.read_bytes()
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "diff_input": SIMPLE_DIFF,
        "dry_run": True,
        "runtime": runtime,
    })
    assert any(phrase in result.lower() for phrase in ("patching file", "patch applied", "checking file"))
    assert target.read_bytes() == before


async def test_patch_file_diff_input_backup_creates_orig(tmp_path):
    """With *backup=True* an .orig file must be left behind."""
    _write_hello(tmp_path)
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "diff_input": SIMPLE_DIFF,
        "backup": True,
        "runtime": runtime,
    })
    assert "patching file" in result.lower() or "patch applied" in result.lower()
    assert (tmp_path / "hello.txt.orig").exists()


async def test_patch_file_diff_input_strip_level(tmp_path):
    """Verify that strip level is forwarded to patch -p."""
    target = _write_hello(tmp_path)
    diff_no_path = """\
--- hello.txt
+++ hello.txt
@@ -1,3 +1,3 @@
 Hello
-World
+Universe
 Goodbye
"""
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "diff_input": diff_no_path,
        "strip_level": 0,
        "runtime": runtime,
    })
    assert "patching file" in result.lower() or "patch applied" in result.lower()
    assert target.read_text() == "Hello\nUniverse\nGoodbye\n"


async def test_patch_file_diff_input_empty_returns_error(tmp_path):
    """Empty *diff_input* must be rejected."""
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "diff_input": "",
        "runtime": runtime,
    })
    assert "error:" in result


async def test_patch_file_diff_input_whitespace_only_returns_error(tmp_path):
    """Whitespace-only *diff_input* must be rejected."""
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "diff_input": "   \n  \t  ",
        "runtime": runtime,
    })
    assert "error:" in result


async def test_patch_file_rejects_missing_diff_input(tmp_path):
    """Providing neither *diff_input* must be rejected."""
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "runtime": runtime,
    })
    assert "error:" in result


async def test_patch_file_diff_input_invalid_diff_returns_error(tmp_path):
    """A malformed unified diff must produce an error, not crash."""
    _write_hello(tmp_path)
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "diff_input": "this is not a diff at all",
        "runtime": runtime,
    })
    assert "error:" in result


async def test_patch_file_diff_input_mismatched_content_returns_error(tmp_path):
    """A valid diff whose context does not match the file must produce an error."""
    _write_hello(tmp_path, "Completely different content\n")
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "diff_input": SIMPLE_DIFF,
        "runtime": runtime,
    })
    assert "error:" in result


# ── Timeout test ────────────────────────────────────────────────────────────


async def test_apply_patch_command_timeout(tmp_path):
    """The subprocess must be killed and an error returned on timeout."""
    _write_hello(tmp_path)

    class _FakeProc:
        def communicate(self, input=b""):
            # Must be sync: the coroutine is created before ``wait_for`` is
            # called, and if ``wait_for`` raises ``TimeoutError`` the coroutine
            # is never awaited — an async version triggers
            # ``RuntimeWarning: coroutine was never awaited``.
            return (b"", b"")

        def kill(self):
            pass

    fake_runtime = rt(tmp_path)
    with (
        mock_patch("openbot.tools.builtin.files.asyncio.wait_for", side_effect=TimeoutError),
        mock_patch("openbot.tools.builtin.files.asyncio.create_subprocess_exec", return_value=_FakeProc()),
    ):
        result = await _apply_patch_command(
            patch_content=SIMPLE_DIFF,
            path=None,
            dry_run=False,
            backup=False,
            strip_level=1,
            runtime=fake_runtime,
            timeout=1.0,
        )
    assert "timed out" in result.lower() or "error:" in result.lower()
