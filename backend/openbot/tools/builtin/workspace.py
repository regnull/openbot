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
    """Validate a relative workspace path or a home-relative path such as ``~/work/core-web``."""
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
    if Path(raw).is_absolute() and not home_relative:
        raise ValueError("working_directory must be relative to the workspace root")
    # Home-relative paths must not traverse above the user's home directory.
    if home_relative and any(part == ".." for part in Path(raw[1:]).parts):
        raise ValueError("working_directory cannot contain '..'")
    if home_relative:
        target = Path(os.path.expanduser(raw)).resolve()
        if not target.exists():
            raise ValueError(f"working_directory does not exist: {directory}")
        if not target.is_dir():
            raise ValueError(f"working_directory is not a directory: {directory}")
        return raw.replace("\\", "/")
    target = resolve_in_workspace(root, raw)
    if not target.exists():
        raise ValueError(f"working_directory does not exist: {directory}")
    if not target.is_dir():
        raise ValueError(f"working_directory is not a directory: {directory}")
    rel = target.relative_to(root.resolve())
    return rel.as_posix() if rel.parts else None


def thread_workspace_root(root: Path, directory: str | None) -> Path:
    if directory and _is_home_relative(directory):
        return Path(os.path.expanduser(directory)).resolve()
    return resolve_in_workspace(root, directory)
