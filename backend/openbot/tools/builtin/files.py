import asyncio
import difflib
import os
import sys
from pathlib import Path

from langchain.tools import ToolRuntime, tool

from openbot.tools.builtin.git_for_windows import INSTALL_HINT, find_git_patch
from openbot.tools.builtin.workspace import STATE_DIR, cap, resolve_in_workspace
from openbot.tools.context import RunContext


def _outline(path: str, lines: list[str], size: int, limit: int) -> str:
    """What a whole-file read returns when the file is over the cap.

    A head-and-tail dump at the cap is content the model cannot use, and in practice it re-reads the
    file by ranges straight after, so the dump is paid for twice on every later turn. Show the size,
    the start (a third of the cap at most), and how to read the rest."""
    budget = limit // 3
    shown: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        shown.append(line)
        used += len(line) + 1
    head = "\n".join(shown)
    return (
        f"{path}: {len(lines)} lines, {size} chars; too large to show whole (cap {limit} chars). "
        f"Read it in parts with start_line/end_line, or grep for what you need. Lines 1-{len(shown)}:\n{head}"
    )


@tool
async def read_file(
    path: str,
    runtime: ToolRuntime[RunContext],
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read a UTF-8 text file at a path relative to the workspace root.

    Pass `start_line` and/or `end_line` (1-based, inclusive) to read only part of a large file; the
    reply says how many lines the file has. Long results are truncated, so prefer a range over
    re-reading a file you have already seen."""
    try:
        p = resolve_in_workspace(runtime.context.workspace_root, path)
        text = p.read_text(encoding="utf-8", errors="replace")
    except (ValueError, OSError) as e:
        return f"error: {e}"
    limit = runtime.context.tool_output_cap
    lines = text.splitlines()
    total = len(lines)
    if start_line is None and end_line is None:
        if len(text) <= limit:
            return text
        return _outline(path, lines, len(text), limit)
    start = max(1, start_line or 1)
    end = min(total, end_line or total)
    if start > end:
        return f"error: no lines in range {start}-{end} (file has {total} lines)"
    body = "\n".join(lines[start - 1:end])
    return cap(
        f"lines {start}-{end} of {total}:\n{body}", limit, hint="ask for a narrower line range"
    )


@tool
async def write_file(path: str, content: str, runtime: ToolRuntime[RunContext]) -> str:
    """Write (create or overwrite) a UTF-8 text file at a path relative to the workspace root."""
    try:
        p = resolve_in_workspace(runtime.context.workspace_root, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} chars to {path}"
    except (ValueError, OSError) as e:
        return f"error: {e}"


_EDIT_LOCKS: dict[Path, asyncio.Lock] = {}


def _edit_lock(path: Path) -> asyncio.Lock:
    return _EDIT_LOCKS.setdefault(path, asyncio.Lock())


def _decode_escapes(text: str) -> str:
    return bytes(text, "utf-8").decode("unicode_escape")


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _remove_common_indent(text: str) -> str:
    lines = text.split("\n")
    indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    indent = min(indents, default=0)
    return "\n".join(line[indent:] if line.strip() else line for line in lines)


def _candidate_ranges(content: str, old: str) -> list[tuple[int, int, str]]:
    """Return (start, end, strategy) candidates, ordered from strict to fuzzy.

    The matcher ladder is adapted from OpenCode's MIT-licensed edit tool.
    """
    if not old:
        return []
    exact = []
    start = 0
    while True:
        index = content.find(old, start)
        if index < 0:
            break
        exact.append((index, index + len(old), "exact"))
        start = index + max(1, len(old))
    if exact:
        return exact

    content_lines = content.split("\n")
    old_lines = old.split("\n")
    if not old_lines:
        return []
    decoded_old = _decode_escapes(old)
    if decoded_old != old:
        decoded_matches = _candidate_ranges(content, decoded_old)
        if decoded_matches:
            return [(start, end, "escape-normalized") for start, end, _ in decoded_matches]
    if len(old_lines) == 1:
        normalized_old = _normalize_whitespace(old)
        for line_number in range(len(content_lines)):
            for end_line in range(line_number, len(content_lines)):
                block = "\n".join(content_lines[line_number : end_line + 1])
                if _normalize_whitespace(block) == normalized_old:
                    start = sum(len(item) + 1 for item in content_lines[:line_number])
                    return [(start, start + len(block), "whitespace-normalized")]
    strategies = (
        (
            "trimmed lines",
            lambda block: (
                [line.strip() for line in block.split("\n")] == [line.strip() for line in old_lines]
            ),
        ),
        (
            "whitespace-normalized",
            lambda block: _normalize_whitespace(block) == _normalize_whitespace(old),
        ),
        (
            "indentation-flexible",
            lambda block: _remove_common_indent(block) == _remove_common_indent(old),
        ),
        ("escape-normalized", lambda block: block == _decode_escapes(old)),
    )
    for strategy, matches in strategies:
        found: list[tuple[int, int, str]] = []
        for line_number in range(len(content_lines) - len(old_lines) + 1):
            block = "\n".join(content_lines[line_number : line_number + len(old_lines)])
            if matches(block):
                start = sum(len(line) + 1 for line in content_lines[:line_number])
                found.append((start, start + len(block), strategy))
        if found:
            return found

    if len(old_lines) >= 3:
        first, last = old_lines[0].strip(), old_lines[-1].strip()
        found: list[tuple[int, int, str]] = []
        for line_number in range(len(content_lines)):
            if content_lines[line_number].strip() != first:
                continue
            for end_line in range(line_number + 2, len(content_lines)):
                if content_lines[end_line].strip() != last:
                    continue
                block_lines = content_lines[line_number : end_line + 1]
                if len(block_lines) != len(old_lines):
                    continue
                middle = sum(
                    a.strip() == b.strip()
                    for a, b in zip(block_lines[1:-1], old_lines[1:-1], strict=True)
                )
                total = sum(
                    bool(a.strip() or b.strip())
                    for a, b in zip(block_lines[1:-1], old_lines[1:-1], strict=True)
                )
                if not total or middle / total >= 0.5:
                    start = sum(len(line) + 1 for line in content_lines[:line_number])
                    block = "\n".join(block_lines)
                    found.append((start, start + len(block), "first/last-line anchors"))
        if found:
            return found
    return []


def _is_disproportionate(candidate: str, old: str) -> bool:
    return len(candidate) > max(len(old) * 3, len(old) + 200)


def _render_edit_diff(path: str, before: str, after: str, limit: int = 4000) -> str:
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )
    return diff[:limit] + ("\n... diff truncated" if len(diff) > limit else "")


@tool
async def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    runtime: ToolRuntime[RunContext],
    replace_all: bool = False,
) -> str:
    """Replace text in a UTF-8 workspace file using a safe fuzzy matcher ladder."""
    try:
        p = resolve_in_workspace(runtime.context.workspace_root, path)
    except ValueError as e:
        return f"error: {e}"
    if not old_string:
        return "error: 'old_string' must be non-empty"

    async with _edit_lock(p):
        try:
            raw = p.read_bytes()
            bom = raw.startswith(b"\xef\xbb\xbf")
            content = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return f"error: {e}"

        newline = "\r\n" if "\r\n" in content else "\n"
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        old = old_string.replace("\r\n", "\n").replace("\r", "\n")
        new = new_string.replace("\r\n", "\n").replace("\r", "\n")
        matches = _candidate_ranges(normalized, old)
        if not matches:
            return "error: old_string was not found; re-read the file and provide the intended text"
        disproportionate = [
            match for match in matches if _is_disproportionate(normalized[match[0] : match[1]], old)
        ]
        if disproportionate:
            return "error: matched text is much larger than old_string; provide a more specific old_string"
        if len(matches) > 1 and not replace_all:
            return f"error: old_string matched {len(matches)} locations; pass replace_all=true or provide more context"

        selected = matches if replace_all else matches[:1]
        result = normalized
        for start, end, _ in reversed(selected):
            result = result[:start] + new + result[end:]
        output = result.replace("\n", newline)
        encoded = output.encode("utf-8")
        if bom:
            encoded = b"\xef\xbb\xbf" + encoded
        try:
            p.write_bytes(encoded)
        except OSError as e:
            return f"error: {e}"
        strategy = matches[0][2]
        diff = _render_edit_diff(path, normalized, result)
        return (
            f"edited {path} ({strategy}, {len(selected)} replacement{'s' if len(selected) != 1 else ''})\n{diff}"
            if diff
            else f"edited {path} ({strategy})"
        )


async def _apply_patch_command(
    patch_content: str,
    path: str | None,
    dry_run: bool,
    backup: bool,
    strip_level: int,
    runtime: ToolRuntime[RunContext],
    timeout: float = 30.0,
) -> str:
    """Apply a unified diff patch using the system ``patch`` command.

    The diff is piped to ``patch`` via stdin.  *path* (optional) is forwarded as the positional
    file argument so that ``patch`` knows which file(s) to operate on.

    Supported options:
    * ``dry_run``  – ``--dry-run`` – validate the patch without writing.
    * ``backup``   – ``--backup``  – keep originals as ``*.orig``.
    * ``strip_level`` – ``-p<N>``  – leading path-component strip (default 1).
    * ``timeout``  – Maximum seconds to wait for the subprocess (default 30).
    """
    if not patch_content.strip():
        return "error: patch_content is empty"
    if strip_level < 0:
        return f"error: strip_level must be >= 0, got {strip_level}"

    patch = "patch"
    if sys.platform == "win32":
        found = find_git_patch()
        if found is None:
            return INSTALL_HINT.format(tool="patch_file")
        patch = str(found)
    cmd = [patch]
    cmd.append(f"-p{strip_level}")
    if dry_run:
        cmd.append("--dry-run")
    if backup:
        cmd.append("--backup")
    if path:
        # --posix keeps behaviour predictable across platforms.
        cmd.extend(["--posix", path])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(runtime.context.workspace_root),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=patch_content.encode("utf-8")),
            timeout=timeout,
        )
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return f"error: patch command timed out after {timeout}s"

    stdout_text = stdout.decode(errors="replace").strip()
    stderr_text = stderr.decode(errors="replace").strip()

    if proc.returncode != 0:
        details = stderr_text or stdout_text or "(no output)"
        return f"error: patch failed (exit {proc.returncode}): {details}"

    # Build a human-friendly summary from patch's stdout (e.g. "patching file foo.txt").
    summary = stdout_text or "patch applied"
    return summary


@tool
async def patch_file(
    path: str,
    runtime: ToolRuntime[RunContext],
    diff_input: str | None = None,
    dry_run: bool = False,
    backup: bool = False,
    strip_level: int = 1,
) -> str:
    """Apply a unified diff patch to files.

    Pass *path* and *diff_input* (a unified-diff string).  The diff is piped to the
    system ``patch`` command.  Use *dry_run*, *backup* and *strip_level* to control
    the command options.

    The *diff_input* must be a standard unified diff (the format produced by
    ``git diff``, ``diff -u``, etc.)."""
    has_diff = diff_input is not None and len(diff_input) > 0

    if not has_diff:
        return "error: 'diff_input' must be provided and non-empty"

    try:
        p = resolve_in_workspace(runtime.context.workspace_root, path)
    except ValueError as e:
        return f"error: {e}"
    return await _apply_patch_command(
        patch_content=diff_input,  # type: ignore[arg-type]
        path=str(p) if p.is_file() else None,
        dry_run=dry_run,
        backup=backup,
        strip_level=strip_level,
        runtime=runtime,
    )


@tool
async def list_files(runtime: ToolRuntime[RunContext], path: str = ".", depth: int = 2) -> str:
    """List files under a directory (relative to the workspace root) up to `depth` levels.
    Skips .git, node_modules, .venv, __pycache__ and OpenBot's own .openbot state directory."""
    try:
        root = resolve_in_workspace(runtime.context.workspace_root, path)
    except ValueError as e:
        return f"error: {e}"
    if not root.exists():
        return f"error: {path} does not exist"
    skip = {".git", "node_modules", ".venv", "__pycache__", "dist", STATE_DIR}
    lines: list[str] = []
    base_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        level = len(os.path.normpath(dirpath).split(os.sep)) - base_depth
        if level >= depth:
            dirnames[:] = []
        rel = os.path.relpath(dirpath, root)
        for f in sorted(filenames):
            lines.append(f if rel == "." else f"{rel}/{f}")
    return cap(
        "\n".join(lines) or "(empty)",
        runtime.context.tool_output_cap,
        hint="list a subdirectory or a smaller depth",
    )
