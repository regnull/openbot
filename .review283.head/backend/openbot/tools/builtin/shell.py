import asyncio
import os
import signal
import subprocess
import sys

from langchain.tools import ToolRuntime, tool

from openbot.tools.builtin.git_for_windows import INSTALL_HINT, find_git_bash
from openbot.tools.builtin.workspace import cap, resolve_in_workspace
from openbot.tools.context import RunContext

# PATH for commands run as SHELL_USER: the standard one, not the server's (which points at its venv).
SHELL_USER_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _as_shell_user(name: str) -> tuple[list[str], dict[str, str]]:
    """Command prefix and environment that run a command as `name`, seeing none of the server's
    variables (provider keys, SECRET_KEY). Raises KeyError for an unknown user.

    setpriv rather than Popen's user=/group=: uvicorn runs on uvloop, whose subprocess support
    rejects those. setpriv execs the shell in place, so the pid and process group stay the same and
    _kill_group still reaps everything. --no-new-privs keeps setuid binaries like su from getting
    back to root."""
    import pwd  # POSIX only

    entry = pwd.getpwuid(int(name)) if name.isdigit() else pwd.getpwnam(name)
    prefix = ["setpriv", f"--reuid={entry.pw_uid}", f"--regid={entry.pw_gid}", "--init-groups", "--no-new-privs",
              "--"]
    env = {"PATH": SHELL_USER_PATH, "HOME": entry.pw_dir, "USER": entry.pw_name, "LOGNAME": entry.pw_name,
           "LANG": "C.UTF-8"}
    return prefix, env


async def _kill_group(proc: asyncio.subprocess.Process, job=None) -> None:
    if sys.platform == "win32":
        if job is not None:
            job.terminate()
        else:
            # Without a job object, taskkill /T is the next best thing (it misses MSYS background jobs).
            killer = await asyncio.create_subprocess_exec("taskkill", "/pid", str(proc.pid), "/T", "/F",
                                                          stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await killer.wait()
        await proc.wait()
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    await proc.wait()


@tool
async def run_shell(command: str, runtime: ToolRuntime[RunContext], cwd: str | None = None,
                    timeout: int = 120) -> str:
    """Run a shell command (bash) inside the workspace. Use it for git, gh, tests, builds.
    `cwd` is relative to the workspace root. Returns stdout, stderr and the exit code. Output is capped
    tighter than read_file's: do not `cat` or `git show` files through it; read code with read_file
    (start_line/end_line) and pipe long output through `head`, `tail` or `grep`."""
    try:
        workdir = resolve_in_workspace(runtime.context.workspace_root, cwd)
    except ValueError as e:
        return f"error: {e}"
    if sys.platform == "win32":
        bash = find_git_bash()
        if bash is None:
            return INSTALL_HINT.format(tool="run_shell")
        shell, group = str(bash), {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        shell, group = "bash", {"start_new_session": True}
    # With SHELL_USER set, every failure below is an error result: never fall back to running the
    # command as the server user.
    prefix: list[str] = []
    env: dict[str, str] | None = None
    user = runtime.context.shell_user
    if user:
        if sys.platform == "win32":
            return "error: SHELL_USER is not supported on Windows"
        if os.geteuid() != 0:
            return f"error: cannot run commands as SHELL_USER {user!r}: the server has to run as root"
        try:
            prefix, env = _as_shell_user(user)
        except KeyError:
            return f"error: SHELL_USER {user!r} does not exist on this system"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        proc = await asyncio.create_subprocess_exec(
            *prefix, shell, "-lc", command, cwd=str(workdir), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **group)
    except FileNotFoundError:
        if not prefix:
            raise
        return "error: SHELL_USER needs setpriv (util-linux), which isn't installed"
    job = None
    if sys.platform == "win32":
        from openbot.tools.builtin.windows_job import WindowsJob
        job = WindowsJob.attach(proc.pid)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        await _kill_group(proc, job)
        return f"error: command timed out after {timeout}s"
    except asyncio.CancelledError:
        # A cancelled run (user pressed Cancel, or the actor's task was torn down) must not leave the
        # command and everything it spawned running forever. start_new_session put them in their own
        # process group (on Windows: a job object), so one kill reaps the lot; then wait() so no zombie
        # is left behind.
        await _kill_group(proc, job)
        raise
    finally:
        if job is not None:
            job.close()
    parts = [f"exit code: {proc.returncode}"]
    if out:
        parts.append("stdout:\n" + out.decode(errors="replace"))
    if err:
        parts.append("stderr:\n" + err.decode(errors="replace"))
    return cap("\n".join(parts), runtime.context.shell_output_cap,
               hint="pipe through head/tail/grep or use --name-only style flags to get less output; to read code use read_file with a line range",
               workspace_root=runtime.context.workspace_root)
