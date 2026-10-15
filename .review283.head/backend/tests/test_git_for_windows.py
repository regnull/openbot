"""Git for Windows lookup for run_shell and patch_file (#187). Pure path logic, so it runs everywhere."""
from pathlib import Path
from types import SimpleNamespace

from langchain.tools import ToolRuntime

from openbot.tools.builtin import files as files_module
from openbot.tools.builtin import shell as shell_module
from openbot.tools.builtin.files import _apply_patch_command
from openbot.tools.builtin.git_for_windows import find_git_bash, find_git_patch, git_install_roots
from openbot.tools.builtin.shell import run_shell
from openbot.tools.context import RunContext


def git_install(root: Path, *, bin_bash: bool = True, usr_bash: bool = True, patch: bool = True) -> Path:
    for rel, wanted in (("bin/bash.exe", bin_bash), ("usr/bin/bash.exe", usr_bash), ("usr/bin/patch.exe", patch),
                        ("cmd/git.exe", True)):
        if wanted:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("")
    return root


def no_git(*_args, **_kwargs) -> None:
    return None


def test_prefers_the_install_next_to_git_on_path(tmp_path):
    on_path = git_install(tmp_path / "custom" / "Git")
    git_install(tmp_path / "ProgramFiles" / "Git")
    env = {"PATH": "x", "ProgramFiles": str(tmp_path / "ProgramFiles")}
    which = lambda *_a, **_k: str(on_path / "cmd" / "git.exe")
    assert find_git_bash(env, which) == on_path / "bin" / "bash.exe"
    assert find_git_patch(env, which) == on_path / "usr" / "bin" / "patch.exe"


def test_git_in_mingw64_bin_still_finds_its_install(tmp_path):
    root = git_install(tmp_path / "Git")
    (root / "mingw64" / "bin").mkdir(parents=True)
    which = lambda *_a, **_k: str(root / "mingw64" / "bin" / "git.exe")
    assert find_git_bash({}, which) == root / "bin" / "bash.exe"


def test_falls_back_to_the_standard_install_locations_in_order(tmp_path):
    env = {"ProgramFiles": str(tmp_path / "pf"), "ProgramFiles(x86)": str(tmp_path / "pf86"),
           "LOCALAPPDATA": str(tmp_path / "local")}
    assert git_install_roots(env, no_git) == [tmp_path / "pf" / "Git", tmp_path / "pf86" / "Git",
                                              tmp_path / "local" / "Programs" / "Git"]
    user_scope = git_install(tmp_path / "local" / "Programs" / "Git")
    assert find_git_bash(env, no_git) == user_scope / "bin" / "bash.exe"
    x86 = git_install(tmp_path / "pf86" / "Git")
    assert find_git_bash(env, no_git) == x86 / "bin" / "bash.exe"


def test_prefers_bin_bash_over_usr_bin_bash(tmp_path):
    root = git_install(tmp_path / "pf" / "Git", bin_bash=False)
    env = {"ProgramFiles": str(tmp_path / "pf")}
    assert find_git_bash(env, no_git) == root / "usr" / "bin" / "bash.exe"
    (root / "bin").mkdir()
    (root / "bin" / "bash.exe").write_text("")
    assert find_git_bash(env, no_git) == root / "bin" / "bash.exe"


def test_never_falls_back_to_the_wsl_launcher_on_path(tmp_path):
    """System32\\bash.exe relays into WSL. Without Git for Windows there is no bash, not that one."""
    system32 = tmp_path / "Windows" / "System32"
    system32.mkdir(parents=True)
    (system32 / "bash.exe").write_text("")
    assert find_git_bash({"PATH": str(system32)}, no_git) is None


def test_patch_needs_patch_exe_in_the_same_install(tmp_path):
    git_install(tmp_path / "pf" / "Git", patch=False)
    git_install(tmp_path / "local" / "Programs" / "Git")
    env = {"ProgramFiles": str(tmp_path / "pf"), "LOCALAPPDATA": str(tmp_path / "local")}
    assert find_git_patch(env, no_git) is None


def rt(root: Path) -> ToolRuntime:
    root.mkdir(parents=True, exist_ok=True)
    return ToolRuntime(context=RunContext("b", "bot", "Bot", "t", "r", root.resolve(), None), store=None, state={},
                       tool_call_id="c", config={}, stream_writer=lambda *_: None)


async def test_tools_tell_the_bot_to_install_git_for_windows(tmp_path, monkeypatch):
    """The hint is the tool result, so the bot can pass it on instead of it only reaching the log."""
    for module, finder in ((shell_module, "find_git_bash"), (files_module, "find_git_patch")):
        monkeypatch.setattr(module, "sys", SimpleNamespace(platform="win32"))
        monkeypatch.setattr(module, finder, lambda: None)
    out = await run_shell.ainvoke({"command": "echo hi", "runtime": rt(tmp_path)})
    assert out.startswith("error: run_shell needs Git for Windows") and "git-scm.com" in out
    out = await _apply_patch_command("--- a/x\n+++ b/x\n", None, False, False, 1, rt(tmp_path))
    assert out.startswith("error: patch_file needs Git for Windows") and "git-scm.com" in out
