from pathlib import Path

import pytest
from langchain.tools import ToolRuntime

from openbot.tools.builtin import SELECTABLE_TOOLS
from openbot.tools.builtin.files import patch_file
from openbot.tools.context import RunContext


def rt(root: Path) -> ToolRuntime:
    root.mkdir(parents=True, exist_ok=True)
    context = RunContext("b", "bot", "Bot", "t", "r", root.resolve(), None)
    return ToolRuntime(context=context, store=None, state={}, tool_call_id="c", config={}, stream_writer=lambda *_: None)


async def test_patch_file_small_and_multiple_edits_preserves_newlines(tmp_path):
    target = tmp_path / "note.txt"
    target.write_bytes(b"one\r\ntwo\r\n")
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({"path": "note.txt", "edits": [{"old": "one", "new": "1"}, {"old": "two", "new": "2"}], "runtime": runtime})
    assert result == "patched note.txt (2 edits)"
    assert target.read_bytes() == b"1\r\n2\r\n"


async def test_patch_file_rejects_overlapping_anchors_atomically(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("abc")
    before = target.read_bytes()
    result = await patch_file.ainvoke({"path": "note.txt", "edits": [{"old": "ab", "new": "AB"}, {"old": "bc", "new": "BC"}], "runtime": rt(tmp_path)})
    assert "overlapping anchors" in result
    assert target.read_bytes() == before


@pytest.mark.parametrize(("content", "old", "message"), [("one", "missing", "not found"), ("one one", "one", "ambiguous")])
async def test_patch_file_anchor_errors_are_atomic(tmp_path, content, old, message):
    target = tmp_path / "note.txt"
    target.write_text(content)
    before = target.read_bytes()
    result = await patch_file.ainvoke({"path": "note.txt", "edits": [{"old": old, "new": "changed"}], "runtime": rt(tmp_path)})
    assert message in result
    assert target.read_bytes() == before


async def test_patch_file_late_failure_and_invalid_path_are_atomic(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("one\ntwo")
    before = target.read_bytes()
    runtime = rt(tmp_path)
    result = await patch_file.ainvoke({"path": "note.txt", "edits": [{"old": "one", "new": "x"}, {"old": "missing", "new": "y"}], "runtime": runtime})
    assert "not found" in result and target.read_bytes() == before
    result = await patch_file.ainvoke({"path": "../note.txt", "edits": [{"old": "one", "new": "x"}], "runtime": runtime})
    assert result.startswith("error:") and target.read_bytes() == before


def test_patch_file_is_selectable():
    assert "patch_file" in [tool.name for tool in SELECTABLE_TOOLS]
