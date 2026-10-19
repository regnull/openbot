"""Per-run workspace snapshots.

Records which files a run changed and the diff, without touching the workspace's
own git state.  The approach is ported from OpenCode's `snapshot/` service
(MIT-licensed, https://github.com/anomalyco/opencode/blob/dev/packages/core/src/snapshot.ts
and packages/core/src/git.ts):

- One dedicated, bare-ish git repository per workspace (the "store") lives under
  OpenBot's state directory (`.openbot/snapshots/<hash>`), keyed by the resolved
  workspace root.  It is created with `git init` using a redirected GIT_DIR, so
  the workspace's own `.git` is never touched: no refs, no objects, no index in
  the repo the bot works in.
- A snapshot is `git add -A` + `git write-tree` against the store: the resulting
  tree ID is a content-addressed fingerprint of the whole workspace tree.
- Capturing before and after a run and diffing the two trees
  (`git diff-tree --name-status` / `-p`) yields exactly the files that run's
  tools changed, and the unified diff.

The store's index is a pure cache that is rebuilt from the worktree on every
capture, so concurrent runs (several bots sharing one workspace) never corrupt
it: captures may interleave, and git's index is only ever read+replaced, never
merged, by this code.  Object writes take git's cross-process lock, and we
serialize captures per store in-process as well.

Revert is intentionally out of scope: several bots share one workspace, so
reverting one run's snapshot would wipe out the other bots' edits.

The workspace's own ignore rules (`.gitignore`, `.git/info/exclude`, global
excludes) apply to the capture, exactly as they do to OpenCode's snapshot store;
`.openbot` is additionally always excluded via the store's `info/exclude`, so a
run can never record OpenBot's own state as one of its changes.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from openbot.config import Settings
from openbot.tools.builtin.workspace import thread_workspace_root

log = logging.getLogger(__name__)

# Git store tuning, from OpenCode's snapshot config (packages/core/src/git.ts):
# stable hashing, no autocrlf mangling, larger indexes for big worktrees, and no
# fsmonitor (the store is only written through our own short-lived commands).
_STORE_CONFIG = {
    "core.autocrlf": "false",
    "core.longpaths": "true",
    "core.symlinks": "true",
    "core.fsmonitor": "false",
    "core.untrackedCache": "true",
    "feature.manyFiles": "true",
    "index.version": "4",
    "index.threads": "true",
}

# Statuses that ended a run; only these get the after-capture (a run paused on a
# human is not done, and a resume continues the same run against the same
# before-tree).  Statuses that never started doing work have no before-tree.
_END_STATUSES = ("completed", "failed", "cancelled")

# In-process serialization per store dir: several bots share one workspace, so
# captures from concurrent runs must not interleave index writes.  git itself
# would serialize them via index.lock; this avoids the error path entirely.
_LOCK_REGISTRY: dict[str, asyncio.Lock] = {}
_LOCK_REGISTRY_GUARD = asyncio.Lock()


def _store_lock(store_dir: Path) -> asyncio.Lock:
    key = str(store_dir)
    lock = _LOCK_REGISTRY.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCK_REGISTRY[key] = lock
    return lock


@dataclass(frozen=True)
class RunDiff:
    """The files one run changed, and the unified diff, in stable order."""

    changed_files: list[str]
    diff: str  # "" means no changes (or the diff could not be produced)


def snapshot_store_dir(settings: Settings, workspace_root: Path) -> Path | None:
    """Where this workspace's snapshot store lives, or None when there is no state dir.

    The store is keyed by a hash of the resolved workspace root so concurrent bots
    sharing the app (each with its own thread working directory) land in one store
    per workspace, never in the workspace itself.
    """
    state_dir = settings.state_dir
    if state_dir is None:
        return None
    root = workspace_root.resolve()
    key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    return state_dir / "snapshots" / key


@dataclass
class _Git:
    """Thin async wrapper around one `git` subprocess invocation."""

    args: list[str]
    cwd: Path | None = None
    env: dict[str, str] | None = None
    input: str | bytes | None = None

    async def run(self) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *self.args,
            cwd=str(self.cwd) if self.cwd else None,
            env=self.env,
            stdin=asyncio.subprocess.PIPE if self.input is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(
            self.input.encode("utf-8") if isinstance(self.input, str) else self.input
        )
        return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


class SnapshotStore:
    """The per-workspace snapshot git repository (see module docstring)."""

    def __init__(self, settings: Settings, workspace_root: Path) -> None:
        self.settings = settings
        self.workspace_root = workspace_root.resolve()
        store = snapshot_store_dir(settings, self.workspace_root)
        if store is None:
            raise RuntimeError("snapshots need a state directory (set OPENBOT_ROOT_DIRECTORY)")
        self.store_dir = store
        self._lock = _store_lock(store)

    @property
    def _base_args(self) -> list[str]:
        return ["--git-dir", str(self.store_dir), "--work-tree", str(self.workspace_root)]

    def _git(self, args: list[str], *, input: str | None = None) -> _Git:
        return _Git(self._base_args + args, cwd=self.workspace_root, input=input)

    async def _ensure_init(self) -> None:
        """Create the store if needed, and pin its config (idempotent, cheap)."""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        if not (self.store_dir / "HEAD").exists():
            # `git init` with GIT_DIR/GIT_WORK_TREE redirected writes the repo
            # directly into the store dir; the workspace's own git is untouched.
            git = _Git(
                ["init"],
                env={"GIT_DIR": str(self.store_dir), "GIT_WORK_TREE": str(self.workspace_root)},
                cwd=self.workspace_root,
            )
            code, _out, err = await git.run()
            if code != 0:
                raise RuntimeError(f"could not initialize snapshot store: {err.strip()}")
            for key, value in _STORE_CONFIG.items():
                git = self._git(["config", key, value])
                code, _out, err = await git.run()
                if code != 0:
                    raise RuntimeError(f"could not configure snapshot store ({key}): {err.strip()}")
        # Never record OpenBot's own state as a run's change, even in workspaces
        # whose .gitignore does not list .openbot.
        exclude = self.store_dir / "info" / "exclude"
        try:
            text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
            lines = [line.strip() for line in text.splitlines()]
            if ".openbot" not in lines:
                exclude.write_text(text.rstrip("\n") + "\n.openbot\n" if text else ".openbot\n", encoding="utf-8")
        except OSError as e:
            log.warning("could not write snapshot store exclude: %s", e)

    async def capture(self) -> str | None:
        """Fingerprint the workspace tree.  None when the store could not be used
        (captures are best effort: a run must never fail because snapshots broke)."""
        try:
            async with self._lock:
                await self._ensure_init()
                git = self._git(["add", "-A"])
                code, _out, err = await git.run()
                if code != 0:
                    log.warning("snapshot add failed for %s: %s", self.workspace_root, err.strip())
                    return None
                git = self._git(["write-tree"])
                code, out, err = await git.run()
                if code != 0:
                    log.warning("snapshot write-tree failed for %s: %s", self.workspace_root, err.strip())
                    return None
                tree = out.strip()
                if not tree:
                    return None
                log.debug("snapshot captured %s at %s", self.workspace_root, tree)
                return tree
        except (OSError, RuntimeError) as e:
            log.warning("snapshot capture failed for %s: %s", self.workspace_root, e)
            return None

    async def diff(self, before: str, after: str) -> RunDiff:
        """Diff two captured trees, returning changed paths and the unified diff.

        Renames are not detected (--no-renames), matching OpenCode: one run's
        delete+recreate of a file shows as delete+add, which is clearer in a
        per-run audit than a rename.
        """
        empty = RunDiff(changed_files=[], diff="")
        try:
            async with self._lock:
                # `--name-status -z` is NUL-safe for odd filenames; the -p diff has
                # no -z form, so unquoted paths keep non-ASCII names matching.
                git = self._git(
                    ["diff-tree", "--no-renames", "--no-commit-id", "--name-status", "-r", "-z", before, after]
                )
                code, out, err = await git.run()
                if code != 0:
                    log.warning("snapshot diff-tree failed for %s: %s", self.workspace_root, err.strip())
                    return empty
                parts = out.split("\0")
                changed: list[str] = []
                for i in range(0, len(parts) - 1, 2):
                    status = parts[i]
                    path = parts[i + 1] if i + 1 < len(parts) else ""
                    if not status or not path:
                        continue
                    if status[0] in ("A", "M", "D"):
                        changed.append(path)
                git = self._git(
                    [
                        "-c", "core.quotepath=false",
                        "diff-tree", "--no-renames", "--no-commit-id", "-p", "--no-ext-diff", before, after,
                    ]
                )
                code, out, err = await git.run()
                if code != 0:
                    log.warning("snapshot diff failed for %s: %s", self.workspace_root, err.strip())
                    return RunDiff(changed_files=changed, diff="")
                return RunDiff(changed_files=changed, diff=out.rstrip("\n"))
        except (OSError, RuntimeError) as e:
            log.warning("snapshot diff failed for %s: %s", self.workspace_root, e)
            return empty


def _workspace_root_for_thread(settings: Settings, thread) -> Path:
    """The resolved workspace root a run works in (same derivation as the runner)."""
    return thread_workspace_root(settings.workspace_root, thread.working_directory)


def store_for_run(settings: Settings, thread) -> SnapshotStore | None:
    """A ready-to-use SnapshotStore for a run's thread, or None when unsupported."""
    try:
        return SnapshotStore(settings, _workspace_root_for_thread(settings, thread))
    except (RuntimeError, ValueError):
        return None