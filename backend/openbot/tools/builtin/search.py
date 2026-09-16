from __future__ import annotations

import re
from pathlib import Path

from langchain.tools import ToolRuntime, tool

from openbot.tools.builtin.workspace import cap, resolve_in_workspace
from openbot.tools.context import RunContext

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next",
             ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage", ".turbo"}
MAX_FILE_BYTES = 2_000_000


def _is_text(data: bytes) -> bool:
    return b"\x00" not in data[:8000]


def _iter_files(root: Path, glob: str | None):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob(glob or "*")):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        yield p


@tool
async def search_code(pattern: str, runtime: ToolRuntime[RunContext], path: str | None = None, glob: str | None = None,
                      context: int = 0, max_results: int = 40) -> str:
    """Search files under the workspace for a regular expression and return only the matching lines as
    `path:line: text`, so you can locate code without reading whole files. `path` narrows to a directory or
    one file (relative to the workspace root); `glob` filters file names (e.g. `*.py`); `context` adds that
    many lines before and after each match; `max_results` caps the number of matches (default 40).
    Prefer this over `cat`, `grep -r` or reading files top to bottom, then read_file the exact line range."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"error: invalid regular expression: {e}"
    try:
        root = resolve_in_workspace(runtime.context.workspace_root, path)
    except ValueError as e:
        return f"error: {e}"
    if not root.exists():
        return f"error: no such path: {path}"
    ws = runtime.context.workspace_root
    out: list[str] = []
    hits = 0
    for f in _iter_files(root, glob):
        try:
            if f.stat().st_size > MAX_FILE_BYTES:
                continue
            data = f.read_bytes()
        except OSError:
            continue
        if not _is_text(data):
            continue
        lines = data.decode("utf-8", errors="replace").splitlines()
        rel = f.relative_to(ws).as_posix() if f.is_relative_to(ws) else str(f)
        for i, line in enumerate(lines, 1):
            if not rx.search(line):
                continue
            hits += 1
            if hits > max_results:
                break
            if context:
                lo, hi = max(1, i - context), min(len(lines), i + context)
                block = "\n".join(f"{'>' if n == i else ' '} {lines[n - 1]}" for n in range(lo, hi + 1))
                out.append(f"{rel}:{lo}-{hi}:\n{block}")
            else:
                out.append(f"{rel}:{i}: {line}")
        if hits > max_results:
            break
    if not out:
        return "(no matches)"
    if hits > max_results:
        out.append(f"... [{max_results} shown; more matches exist. Narrow the pattern, path or glob]")
    return cap("\n".join(out), runtime.context.tool_output_cap, hint="narrow the pattern, path or glob, or lower max_results")
