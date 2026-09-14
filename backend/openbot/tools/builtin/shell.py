import asyncio

from langchain.tools import ToolRuntime, tool

from openbot.tools.builtin.workspace import cap, resolve_in_workspace
from openbot.tools.context import RunContext


@tool
async def run_shell(command: str, runtime: ToolRuntime[RunContext], cwd: str | None = None,
                    timeout: int = 120) -> str:
    """Run a shell command (bash) inside the workspace. Use it for git, gh, tests, builds.
    `cwd` is relative to the workspace root. Returns stdout, stderr and the exit code."""
    try:
        workdir = resolve_in_workspace(runtime.context.workspace_root, cwd)
    except ValueError as e:
        return f"error: {e}"
    workdir.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "bash", "-lc", command, cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return f"error: command timed out after {timeout}s"
    parts = [f"exit code: {proc.returncode}"]
    if out:
        parts.append("stdout:\n" + out.decode(errors="replace"))
    if err:
        parts.append("stderr:\n" + err.decode(errors="replace"))
    return cap("\n".join(parts))
