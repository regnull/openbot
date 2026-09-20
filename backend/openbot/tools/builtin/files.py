import asyncio
import itertools
import os
import tempfile

from langchain.tools import ToolRuntime, tool

from openbot.tools.builtin.workspace import cap, resolve_in_workspace
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
    return (f"{path}: {len(lines)} lines, {size} chars; too large to show whole (cap {limit} chars). "
            f"Read it in parts with start_line/end_line, or grep for what you need. Lines 1-{len(shown)}:\n{head}")


@tool
async def read_file(path: str, runtime: ToolRuntime[RunContext], start_line: int | None = None,
                    end_line: int | None = None) -> str:
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
    return cap(f"lines {start}-{end} of {total}:\n{body}", limit, hint="ask for a narrower line range")


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

    cmd = ["patch"]
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
    edits: list[dict[str, str]] | None = None,
    diff_input: str | None = None,
    dry_run: bool = False,
    backup: bool = False,
    strip_level: int = 1,
) -> str:
    """Apply exact text replacements or a unified diff patch to files.

    **Mode 1 – exact replacements (original behaviour):**
    Pass *path* and *edits* (a list of ``{"old": ..., "new": ...}`` dicts).
    Each ``old`` string must occur exactly once in the file; all validation happens
    before the file is replaced.

    **Mode 2 – unified diff via the system ``patch`` command:**
    Pass *path* and *diff_input* (a unified-diff string).  The diff is piped to the
    ``patch`` command.  Use *dry_run*, *backup* and *strip_level* to control
    the command options.

    Exactly one of *edits* or *diff_input* must be provided."""
    # ── Mode selection ──────────────────────────────────────────────────
    has_edits = edits is not None and len(edits) > 0
    has_diff = diff_input is not None and len(diff_input) > 0

    if has_edits and has_diff:
        return "error: provide either 'edits' or 'diff_input', not both"
    if not has_edits and not has_diff:
        return "error: either 'edits' or 'diff_input' must be provided"

    # ── Mode 2: unified diff via system patch ───────────────────────────
    if has_diff:
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

    # ── Mode 1: exact replacements (original logic) ─────────────────────
    assert edits is not None  # for type-checker
    try:
        p = resolve_in_workspace(runtime.context.workspace_root, path)
        if not p.is_file():
            raise OSError(f"file does not exist or is not a regular file: {path}")
        if not edits:
            raise ValueError("edits must contain at least one replacement")
        raw = p.read_bytes()
        text = raw.decode("utf-8")
        anchors: list[tuple[str, str, int, int]] = []
        for index, edit in enumerate(edits, 1):
            if not isinstance(edit, dict) or not isinstance(edit.get("old"), str) or not isinstance(edit.get("new"), str):
                raise TypeError(f"edit {index} must contain string 'old' and 'new' fields")
            old, new = edit["old"], edit["new"]
            if not old:
                raise ValueError(f"edit {index} has an empty anchor")
            positions: list[int] = []
            offset = 0
            while True:
                match = text.find(old, offset)
                if match == -1:
                    break
                positions.append(match)
                offset = match + 1
            if not positions:
                raise ValueError(f"edit {index} anchor was not found")
            if len(positions) != 1:
                raise ValueError(f"edit {index} anchor is ambiguous ({len(positions)} matches)")
            start = positions[0]
            anchors.append((old, new, start, start + len(old)))
        if len({old for old, _, _, _ in anchors}) != len(anchors):
            raise ValueError("edits must not contain duplicate anchors")
        ordered = sorted(anchors, key=lambda anchor: anchor[2])
        for previous, current in itertools.pairwise(ordered):
            if current[2] < previous[3]:
                raise ValueError("edits contain overlapping anchors")
        patched = text
        for old, new, _, _ in reversed(ordered):
            patched = patched.replace(old, new, 1)
        encoded = patched.encode("utf-8")
        mode = p.stat().st_mode
        fd, temp_name = tempfile.mkstemp(prefix=f".{p.name}.", dir=p.parent)
        try:
            with os.fdopen(fd, "wb") as temp:
                temp.write(encoded)
                temp.flush()
                os.fsync(temp.fileno())
            os.chmod(temp_name, mode)
            os.replace(temp_name, p)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return f"patched {path} ({len(anchors)} edit{'s' if len(anchors) != 1 else ''})"
    except (UnicodeDecodeError, ValueError, OSError, TypeError) as e:
        return f"error: {e}"


@tool
async def list_files(runtime: ToolRuntime[RunContext], path: str = ".", depth: int = 2) -> str:
    """List files under a directory (relative to the workspace root) up to `depth` levels.
    Skips .git, node_modules, .venv and __pycache__."""
    try:
        root = resolve_in_workspace(runtime.context.workspace_root, path)
    except ValueError as e:
        return f"error: {e}"
    if not root.exists():
        return f"error: {path} does not exist"
    skip = {".git", "node_modules", ".venv", "__pycache__", "dist"}
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
    return cap("\n".join(lines) or "(empty)", runtime.context.tool_output_cap, hint="list a subdirectory or a smaller depth")
