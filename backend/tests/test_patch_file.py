"""Tests for the ``patch_file`` tool.

Covers:
1. Exact-replacement mode (original behaviour)
2. Unified-diff (``diff_input``) mode with the system ``patch`` command
3. Dry-run, backup, strip-level options
4. Error handling: empty input, invalid patches, mutual exclusivity, timeouts
5. Edge cases: whitespace-only input, malformed diffs
"""
from __future__ import annotations

import asyncio
import stat
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

# ── Existing tests (exact-replacement mode, preserved from main) ────────────


async def test_patch_file_small_and_multiple_edits_preserves_newlines(tmp_path):
    target = tmp_path / "note.txt"
    target.write_bytes(b"one\r\ntwo\r\n")
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "note.txt",
        "edits": [{"old": "one", "new": "1"}, {"old": "two", "new": "2"}],
        "runtime": runtime,
    })
    assert result == "patched note.txt (2 edits)"
    assert target.read_bytes() == b"1\r\n2\r\n"


async def test_patch_file_rejects_overlapping_occurrences_atomically(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("aaa")
    before = target.read_bytes()
    result = await patch_file.ainvoke({
        "path": "note.txt",
        "edits": [{"old": "aa", "new": "AA"}],
        "runtime": rt(tmp_path),
    })
    assert "ambiguous (2 matches)" in result
    assert target.read_bytes() == before


async def test_patch_file_rejects_overlapping_anchors_atomically(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("abc")
    before = target.read_bytes()
    result = await patch_file.ainvoke({
        "path": "note.txt",
        "edits": [{"old": "ab", "new": "AB"}, {"old": "bc", "new": "BC"}],
        "runtime": rt(tmp_path),
    })
    assert "overlapping anchors" in result
    assert target.read_bytes() == before


async def test_patch_file_late_failure_and_invalid_path_are_atomic(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("one\ntwo")
    before = target.read_bytes()
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "note.txt",
        "edits": [{"old": "one", "new": "x"}, {"old": "missing", "new": "y"}],
        "runtime": runtime,
    })
    assert "not found" in result and target.read_bytes() == before
    result = await patch_file.ainvoke({
        "path": "../note.txt",
        "edits": [{"old": "one", "new": "x"}],
        "runtime": runtime,
    })
    assert result.startswith("error:") and target.read_bytes() == before


async def test_patch_file_replaces_text(tmp_path):
    target = _write_hello(tmp_path)
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "edits": [{"old": "World", "new": "Universe"}],
        "runtime": runtime,
    })
    assert result == "patched hello.txt (1 edit)"
    assert target.read_text() == "Hello\nUniverse\nGoodbye\n"


async def test_patch_file_rejects_ambiguous_anchor(tmp_path):
    _write_hello(tmp_path, "aaa\n")
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "edits": [{"old": "a", "new": "b"}],
        "runtime": runtime,
    })
    assert "ambiguous" in result


async def test_patch_file_preserves_permissions(tmp_path):
    target = _write_hello(tmp_path)
    target.chmod(0o644)
    original_mode = stat.S_IMODE(target.stat().st_mode)
    runtime = rt(tmp_path)
    await patch_file.ainvoke({
        "path": "hello.txt",
        "edits": [{"old": "World", "new": "Universe"}],
        "runtime": runtime,
    })
    assert stat.S_IMODE(target.stat().st_mode) == original_mode


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
    assert "patching file" in result.lower() or "patch applied" in result.lower()
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


async def test_patch_file_rejects_both_edits_and_diff_input(tmp_path):
    """Providing both *edits* and *diff_input* must be rejected."""
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({
        "path": "hello.txt",
        "edits": [{"old": "a", "new": "b"}],
        "diff_input": SIMPLE_DIFF,
        "runtime": runtime,
    })
    assert "error:" in result and "not both" in result


async def test_patch_file_rejects_neither_edits_nor_diff_input(tmp_path):
    """Providing neither *edits* nor *diff_input* must be rejected."""
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
        async def communicate(self, input=b""):
            await asyncio.sleep(100)
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
