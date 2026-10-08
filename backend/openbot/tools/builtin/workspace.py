import os
import time
import uuid
from pathlib import Path

OUTPUT_CAP = 8000
HEAD_SHARE = 0.7
TOOL_OUTPUT_DIR = ".openbot/tool-output"
TOOL_OUTPUT_RETENTION_SECONDS = 3 * 24 * 60 * 60
# Where OpenBot keeps its own state under a root directory (see config.py): the live SQLite files.
# No in-process tool may open anything in it. Opening the WAL index (openbot.db-shm) from the backend
# process, even read-only, drops the process's POSIX locks on it; the next `sqlite3` a bot runs then
# takes itself for the only connection, checkpoints under the backend, and every open connection
# fails with "database disk image is malformed" (or SIGBUS when the shm is truncated under an mmap).
STATE_DIR = ".openbot"


def _tool_output_path(root: Path) -> Path:
    return root / TOOL_OUTPUT_DIR


def _cleanup_tool_outputs(directory: Path, now: float) -> None:
    try:
        for path in directory.iterdir():
            if path.is_file() and now - path.stat().st_mtime > TOOL_OUTPUT_RETENTION_SECONDS:
                path.unlink()
    except OSError:
        return


def _save_tool_output(text: str, root: Path) -> str | None:
    directory = _tool_output_path(root)
    now = time.time()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _cleanup_tool_outputs(directory, now)
        filename = f"output-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}-{uuid.uuid4().hex}.txt"
        path = directory / filename
        path.write_text(text, encoding="utf-8")
        return f"{TOOL_OUTPUT_DIR}/{filename}"
    except OSError:
        return None


def expand_path(path: str | None) -> str | None:
    return os.path.expanduser(path) if path is not None else None


def _is_home_relative(path: str) -> bool:
    return path == "~" or path.startswith(("~/", "~\\"))


def resolve_in_workspace(root: Path, path: str | None) -> Path:
    root = root.resolve()
    expanded = expand_path(path)
    target = Path(expanded).resolve() if expanded and Path(expanded).is_absolute() else (root / expanded).resolve() if expanded else root
    if target != root and root not in target.parents:
        raise ValueError(f"path escapes workspace root: {path}")
    relative = target.relative_to(root)
    if STATE_DIR in relative.parts and not (relative.parts[:2] == tuple(TOOL_OUTPUT_DIR.split("/"))):
        raise ValueError(f"path is inside the OpenBot state directory ({STATE_DIR}), which tools must not touch: {path}")
    return target


def cap(text: str, limit: int = OUTPUT_CAP, hint: str = "narrow the command or read a smaller range",
        workspace_root: Path | None = None) -> str:
    if len(text) <= limit:
        return text
    full_output = _save_tool_output(text, workspace_root) if workspace_root is not None else None
    file_hint = f"; full output in {full_output}" if full_output else ""
    available = max(0, limit)
    while True:
        head = int(available * HEAD_SHARE)
        tail = available - head
        dropped = len(text) - available
        # Adapted from OpenCode's MIT-licensed tool/truncate.ts.
        marker = f"\n... [truncated {dropped} chars of {len(text)}{file_hint}; {hint}] ...\n"
        next_available = limit - len(marker)
        if next_available >= available or next_available <= 0:
            if next_available <= 0:
                return marker[:limit]
            break
        available = next_available
    return text[:head] + marker + text[-tail:]


def validate_workspace_directory(root: Path, directory: str | None) -> str | None:
    """Validate an accessible relative, absolute, or ``~/`` directory.

    Relative paths retain workspace traversal protection; absolute paths are allowed
    anywhere on the filesystem so a thread is not tied to the server startup tree.
    """
    if directory is None:
        return None
    raw = directory.strip()
    if raw in ("", "."):
        return None
    if "\x00" in raw:
        raise ValueError("working_directory contains an invalid null byte")
    if any(ord(ch) < 32 for ch in raw):
        raise ValueError("working_directory contains control characters")
    home_relative = _is_home_relative(raw)
    if home_relative and any(part == ".." for part in Path(raw[1:]).parts):
        raise ValueError("working_directory cannot contain '..'")
    is_absolute = Path(raw).is_absolute() and not home_relative
    target = (Path(os.path.expanduser(raw)).resolve() if home_relative or is_absolute
              else resolve_in_workspace(root, raw))
    if not target.exists():
        raise ValueError(f"working_directory does not exist: {directory}")
    if not target.is_dir():
        raise ValueError(f"working_directory is not a directory: {directory}")
    if not os.access(target, os.R_OK | os.X_OK):
        raise ValueError(f"working_directory is not accessible: {directory}")
    try:
        next(target.iterdir(), None)
    except OSError as exc:
        raise ValueError(f"working_directory is not accessible: {directory}") from exc
    if home_relative:
        return raw.replace("\\", "/")
    if is_absolute:
        return target.as_posix()
    rel = target.relative_to(root.resolve())
    return rel.as_posix() if rel.parts else None


def thread_workspace_root(root: Path, directory: str | None) -> Path:
    if directory and (_is_home_relative(directory) or Path(directory).is_absolute()):
        return Path(os.path.expanduser(directory)).resolve()
    return resolve_in_workspace(root, directory)


def _parent_of(normalized: str | None) -> str | None:
    if normalized is None or normalized == "~":
        return None
    head, _, _ = normalized.rpartition("/")
    if _is_home_relative(normalized):
        return head or "~"
    return head or "."


def browse_workspace_directory(root: Path, directory: str | None) -> tuple[str, str | None, list[tuple[str, str]]]:
    normalized = validate_workspace_directory(root, directory)
    target = thread_workspace_root(root, normalized)
    here = normalized or "."
    prefix = "" if here == "." else here.rstrip("/") + "/"
    entries: list[tuple[str, str]] = []
    try:
        children = sorted(target.iterdir(), key=lambda c: c.name.lower())
    except OSError as exc:
        raise ValueError(f"working_directory is not readable: {directory}") from exc
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            if not child.is_dir():
                continue
        except OSError:
            continue
        entries.append((child.name, prefix + child.name))
    return here, _parent_of(normalized), entries
