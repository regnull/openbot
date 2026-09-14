import os

from langchain.tools import ToolRuntime, tool

from openbot.tools.builtin.workspace import cap, resolve_in_workspace
from openbot.tools.context import RunContext


@tool
async def read_file(path: str, runtime: ToolRuntime[RunContext]) -> str:
    """Read a UTF-8 text file at a path relative to the workspace root."""
    try:
        p = resolve_in_workspace(runtime.context.workspace_root, path)
        return cap(p.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError) as e:
        return f"error: {e}"


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
    return cap("\n".join(lines) or "(empty)")
