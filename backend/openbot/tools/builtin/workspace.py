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
