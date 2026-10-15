r"""Where run_shell's bash and patch_file's patch come from on Windows.

``bash`` on a Windows PATH usually resolves to ``C:\Windows\System32\bash.exe``, the WSL launcher:
it runs the command inside a Linux distribution with a different view of the filesystem, or fails
with a relay error when no distribution is installed. Windows has no ``patch`` at all. Git for
Windows ships both, so the tools look for that install directly and never resolve ``bash`` through
PATH.
"""
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

INSTALL_HINT = ("error: {tool} needs Git for Windows, which provides bash and patch on Windows. "
                "Install it from https://git-scm.com/download/win, then try again.")

Which = Callable[..., str | None]


def git_install_roots(env: Mapping[str, str] | None = None, which: Which = shutil.which) -> list[Path]:
    """Candidate Git for Windows install directories, in lookup order."""
    env = os.environ if env is None else env
    roots: list[Path] = []
    git = which("git", path=env.get("PATH"))
    if git:
        # git.exe sits in <root>\cmd (what the installer puts on PATH), <root>\bin or <root>\mingw64\bin.
        exe = Path(git)
        roots += [exe.parent.parent, exe.parent.parent.parent]
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        if env.get(var):
            roots.append(Path(env[var]) / "Git")
    if env.get("LOCALAPPDATA"):
        roots.append(Path(env["LOCALAPPDATA"]) / "Programs" / "Git")    # the installer's per-user scope
    return roots


def find_git_install(env: Mapping[str, str] | None = None, which: Which = shutil.which) -> tuple[Path, Path] | None:
    r"""(install directory, bash.exe) of the first Git for Windows install found, or None.

    ``bin\bash.exe`` comes before ``usr\bin\bash.exe``: it is the launcher Git Bash's own terminal
    uses, so a login shell gets the same PATH (mingw64/bin, usr/bin, ...) the user sees there.
    """
    for root in git_install_roots(env, which):
        for bash in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
            if bash.is_file():
                return root, bash
    return None


def find_git_bash(env: Mapping[str, str] | None = None, which: Which = shutil.which) -> Path | None:
    found = find_git_install(env, which)
    return found[1] if found else None


def find_git_patch(env: Mapping[str, str] | None = None, which: Which = shutil.which) -> Path | None:
    """patch.exe from the same Git for Windows install run_shell uses, or None."""
    found = find_git_install(env, which)
    if found is None:
        return None
    patch = found[0] / "usr" / "bin" / "patch.exe"
    return patch if patch.is_file() else None
