from pathlib import Path

OUTPUT_CAP = 20000


def resolve_in_workspace(root: Path, path: str | None) -> Path:
    root = root.resolve()
    target = (root / path).resolve() if path else root
    if target != root and root not in target.parents:
        raise ValueError(f"path escapes workspace root: {path}")
    return target


def cap(text: str, limit: int = OUTPUT_CAP) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def validate_workspace_directory(root: Path, directory: str | None) -> str | None:
    """Return a normalized relative directory under root, or None for the root itself.

    Thread working directories are persisted as POSIX-style relative paths so they remain
    readable in API responses and continue to mean the same thing if WORKSPACE_ROOT is
    configured with an equivalent relative/absolute spelling.
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
    if Path(raw).is_absolute():
        raise ValueError("working_directory must be relative to the workspace root")
    target = resolve_in_workspace(root, raw)
    if not target.exists():
        raise ValueError(f"working_directory does not exist: {directory}")
    if not target.is_dir():
        raise ValueError(f"working_directory is not a directory: {directory}")
    try:
        rel = target.relative_to(root.resolve())
    except ValueError as e:
        raise ValueError(f"working_directory escapes workspace root: {directory}") from e
    return rel.as_posix() if rel.parts else None


def thread_workspace_root(root: Path, directory: str | None) -> Path:
    """Resolve a persisted thread working directory to the actual tool root."""
    return resolve_in_workspace(root, directory)
