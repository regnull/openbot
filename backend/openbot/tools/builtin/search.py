from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

from langchain.tools import ToolRuntime, tool

from openbot.tools.builtin.workspace import STATE_DIR, cap, resolve_in_workspace
from openbot.tools.context import RunContext

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next",
             ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage", ".turbo", STATE_DIR}
MAX_FILE_BYTES = 2_000_000

# Pattern ported from OpenCode tool/grep.ts (MIT license)
_RG_LINE_PATTERN = re.compile(r"^([^:]+:\d+):")


def _is_text(data: bytes) -> bool:
    return b"\x00" not in data[:8000]


# Python fallback: ported from OpenCode tool/glob.ts approach (MIT license)
def _iter_files(root: Path, glob: str | None):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob(glob or "*")):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        yield p


async def _search_code_rg(
    rg: str,
    pattern: str,
    workspace_root: Path,
    root: Path,
    glob: str | None,
    context: int,
    max_results: int,
    runtime: ToolRuntime[RunContext],
) -> str:
    """Use ripgrep for search. Ported from OpenCode tool/grep.ts (MIT license).

    Uses rg's JSON output (--json) so we can distinguish match lines from context
    lines, cap on actual match count (Blocker 2 & 3 fix), and --with-filename so
    single-file searches always include the path prefix (Blocker 1 fix).
    """
    cmd = [
        rg,
        "--json",          # structured output to separate match/context lines
        "--no-heading",
        "--line-number",
        "--with-filename", # always show path prefix (Blocker 1)
    ]
    if glob:
        cmd.extend(["-g", glob])
    if context:
        cmd.extend(["-C", str(context)])
    cmd.extend(["-e", pattern, str(root)])

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=30, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        # Fall back to Python implementation
        return None

    if result.returncode == 2:
        # rg error — fall back to Python
        return None

    if not result.stdout.strip():
        return "(no matches)"

    # Parse JSONL output from rg; count actual match lines (not context lines)
    match_count = 0
    out_lines: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        tp = data.get("type")
        if tp == "match":
            match_count += 1
            if match_count > max_results:
                # We've shown enough matches; stop collecting entirely.
                # Context lines for matches up to max_results have already been
                # included below, so this break is clean.
                break
            path = data["data"]["path"]["text"]
            lineno = data["data"]["line_number"]
            text = data["data"]["lines"]["text"].rstrip("\n")
            # Format: path:line: content (space after colon matches Python fallback)
            out_lines.append(f"{path}:{lineno}: {text}")
        elif tp == "context":
            # Include context lines only while we are still collecting matches
            if match_count <= max_results:
                path = data["data"]["path"]["text"]
                lineno = data["data"]["line_number"]
                text = data["data"]["lines"]["text"].rstrip("\n")
                out_lines.append(f"{path}:{lineno}: {text}")
        # "begin", "end", "summary" are ignored

    if not out_lines:
        return "(no matches)"

    # Sort deterministically by path and line number (Nit 1)
    out_lines.sort()

    suffix = ""
    if match_count > max_results:
        suffix = f"\n... [{max_results} shown; more matches exist. Narrow the pattern, path or glob]"

    return cap(
        "\n".join(out_lines) + suffix,
        runtime.context.tool_output_cap,
        hint="narrow the pattern, path or glob, or lower max_results",
    )


async def _search_code_python(
    pattern: str,
    workspace_root: Path,
    root: Path,
    glob: str | None,
    context: int,
    max_results: int,
    runtime: ToolRuntime[RunContext],
) -> str:
    """Pure-Python file-search fallback when ripgrep is not available."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"error: invalid regular expression: {e}"
    out: list[str] = []
    hits = 0
    for f in _iter_files(root, glob):
        try:
            if f.stat().st_size > MAX_FILE_BYTES:
                continue
            data = f.read_bytes()
        except (OSError, PermissionError):
            continue
        if not _is_text(data):
            continue
        lines = data.decode("utf-8", errors="replace").splitlines()
        rel = f.relative_to(workspace_root).as_posix() if f.is_relative_to(workspace_root) else str(f)
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


@tool
async def search_code(pattern: str, runtime: ToolRuntime[RunContext], path: str | None = None,
                      glob: str | None = None, context: int = 0, max_results: int = 40) -> str:
    """Search files under the workspace for a regular expression and return only the matching lines as
    `path:line: text`, so you can locate code without reading whole files. `path` narrows to a directory or
    one file (relative to the workspace root); `glob` filters file names (e.g. `*.py`); `context` adds that
    many lines before and after each match; `max_results` caps the number of matches (default 40).
    Prefer this over `cat`, `grep -r` or reading files top to bottom, then read_file the exact line range.

    Uses ripgrep (`rg`) when available (respects `.gitignore` and skips hidden files automatically),
    otherwise falls back to a Python walk that does not ignore `.gitignore` or hidden files."""
    try:
        re.compile(pattern)
    except re.error as e:
        return f"error: invalid regular expression: {e}"
    try:
        root = resolve_in_workspace(runtime.context.workspace_root, path)
    except ValueError as e:
        return f"error: {e}"
    if not root.exists():
        return f"error: no such path: {path}"
    ws = runtime.context.workspace_root

    rg = shutil.which("rg")
    if rg is not None:
        result = await _search_code_rg(rg, pattern, ws, root, glob, context, max_results, runtime)
        if result is not None:
            return result
        # rg failed (or timed out) → fall back to Python below

    return await _search_code_python(pattern, ws, root, glob, context, max_results, runtime)


@tool
async def find_files(glob_pattern: str, runtime: ToolRuntime[RunContext], path: str | None = None) -> str:
    """List files matching a glob pattern under the workspace, sorted by modification time (newest first),
    capped at 100 results. Skips binary files, non-text data, and the same junk directories as search_code.

    Ported from OpenCode tool/glob.ts (MIT license)."""
    try:
        root = resolve_in_workspace(runtime.context.workspace_root, path)
    except ValueError as e:
        return f"error: {e}"
    if not root.exists():
        return f"error: no such path: {path}"
    ws = runtime.context.workspace_root

    files: list[tuple[Path, int]] = []  # (path, line_count)
    for p in root.rglob(glob_pattern):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if not _is_text(data):
            continue
        try:
            line_count = data.decode("utf-8", errors="replace").count("\n")
        except (UnicodeDecodeError, ValueError):
            line_count = 0
        files.append((p, line_count))

    if not files:
        return "(no matches)"

    # Sort by mtime descending (newest first), cap at 100
    files.sort(key=lambda t: t[0].stat().st_mtime, reverse=True)
    files = files[:100]

    lines = []
    for f, line_count in files:
        rel = f.relative_to(ws).as_posix() if f.is_relative_to(ws) else str(f)
        lines.append(f"{rel}:{line_count}")

    return cap(
        "\n".join(lines),
        runtime.context.tool_output_cap,
        hint="narrow the glob pattern",
    )