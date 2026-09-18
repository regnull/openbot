import os
from pathlib import Path

OUTPUT_CAP = 8000
HEAD_SHARE = 0.7


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
    return target


def cap(text: str, limit: int = OUTPUT_CAP, hint: str = "narrow the command or read a smaller range") -> str:
    if len(text) <= limit:
        return text
    head = int(limit * HEAD_SHARE)
    tail = limit - head
    dropped = len(text) - head - tail
    return text[:head] + f"\n... [truncated {dropped} chars of {len(text)}; {hint}] ...\n" + text[-tail:]


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
