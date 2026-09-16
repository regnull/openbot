import asyncio
import os
import signal

from langchain.tools import ToolRuntime, tool

from openbot.tools.builtin.workspace import cap, resolve_in_workspace
from openbot.tools.context import RunContext


async def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    await proc.wait()


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
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        await _kill_group(proc)
        return f"error: command timed out after {timeout}s"
    except asyncio.CancelledError:
        # A cancelled run (user pressed Cancel, or the actor's task was torn down) must not leave the
        # command and everything it spawned running forever. start_new_session put them in their own
        # process group, so one killpg reaps the lot; then wait() so no zombie is left behind.
        await _kill_group(proc)
        raise
    parts = [f"exit code: {proc.returncode}"]
    if out:
        parts.append("stdout:\n" + out.decode(errors="replace"))
    if err:
        parts.append("stderr:\n" + err.decode(errors="replace"))
    return cap("\n".join(parts), runtime.context.tool_output_cap,
               hint="pipe through head/tail/grep or use --name-only style flags to get less output")
