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
  (`git diff-tree --name-status` / `-p`) yields the files that changed in the
  workspace while the run was active, and the unified diff.

That is a time window, not attribution: another bot working in the same
workspace, a human's editor or a background build can change files inside the
window too.  `RunWindows` records whether any other run was active in the same
workspace during the window, so the UI can say the changes may not all be this
run's.  The store keeps its index between captures, so a capture after the first
only stats the worktree and hashes the files whose stat changed.

The store's index is a pure cache that is rebuilt from the worktree on every
capture, so concurrent runs (several bots sharing one workspace) never corrupt
it: captures may interleave, and git's index is only ever read+replaced, never
merged, by this code.  Object writes take git's cross-process lock, and we
serialize captures per store in-process as well.

Revert is intentionally out of scope: several bots share one workspace, so
reverting one run's snapshot would wipe out the other bots' edits.

The workspace's `.gitignore` files and the user's global excludes apply to the
capture.  The workspace repo's own `.git/info/exclude` does not: git reads
`info/exclude` from the store's git dir, not the workspace's.  The store's
`info/exclude` always lists `.openbot`, so a run can never record OpenBot's own
state as one of its changes.  A nested git repository inside the workspace is
recorded as a single gitlink, so edits inside it do not show up in the diff.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
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

# A capture walks the whole workspace; one that takes longer than this (a huge or slow
# tree) is abandoned, the git child killed, and the run goes on without a diff.
GIT_TIMEOUT_SECONDS = 120.0

# A leftover index.lock older than this is from a git that died (the backend was killed
# mid-capture); captures are serialized in-process, so nothing of ours still holds it.
STALE_LOCK_SECONDS = 60.0

# The unified diff is stored on the run row; a regenerated lockfile or a generated
# file must not turn one row into megabytes.  Past this many characters the diff is
# cut at a line boundary and marked as truncated (the file list is always complete).
MAX_DIFF_CHARS = 200_000

# In-process serialization per store dir: several bots share one workspace, so
# captures from concurrent runs must not interleave index writes.  git itself
# would serialize them via index.lock; this avoids the error path entirely.
_LOCK_REGISTRY: dict[str, asyncio.Lock] = {}


def _store_lock(store_dir: Path) -> asyncio.Lock:
    key = str(store_dir)
    lock = _LOCK_REGISTRY.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCK_REGISTRY[key] = lock
    return lock


def truncate_diff(diff: str, limit: int = MAX_DIFF_CHARS) -> str:
    """`diff` cut to at most about `limit` characters at a line boundary, with a marker."""
    if len(diff) <= limit:
        return diff
    cut = diff.rfind("\n", 0, limit)
    head = diff[: cut if cut > 0 else limit]
    return f"{head}\n... diff truncated: showing {len(head):,} of {len(diff):,} characters"


class RunWindows:
    """Which runs are active in which workspace, to flag runs whose window overlapped another's.

    A run opens its window just before its before-tree is captured and closes it once its
    after-tree is taken (a run paused on a human stays open: its diff spans the pause).
    Two windows overlap when their roots are the same directory or one contains the other,
    since a thread working in `sub/` edits files a thread working at `.` snapshots.
    `close` answers whether any other run was active in an overlapping root at any point
    during the window.  In memory only: a restart drops open windows with their before-trees.
    """

    def __init__(self) -> None:
        self._active: dict[str, Path] = {}  # run id -> resolved workspace root
        self._shared: set[str] = set()

    @staticmethod
    def _nested(a: Path, b: Path) -> bool:
        return a == b or a in b.parents or b in a.parents

    def open(self, root: Path, run_id: str) -> None:
        root = root.resolve()
        others = [rid for rid, r in self._active.items() if rid != run_id and self._nested(r, root)]
        if others:
            self._shared.add(run_id)
            self._shared.update(others)
        self._active[run_id] = root

    def close(self, root: Path, run_id: str) -> bool:
        self._active.pop(run_id, None)
        shared = run_id in self._shared
        self._shared.discard(run_id)
        return shared


@dataclass(frozen=True)
class RunDiff:
    """The files one run changed, and the unified diff, in stable order."""

    changed_files: list[str]
    diff: str  # "" means no changes (or only the file list could be produced); capped at MAX_DIFF_CHARS


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

    async def run(self, timeout: float = GIT_TIMEOUT_SECONDS) -> tuple[int, str, str]:
        """Run git; on timeout or cancellation the child is killed, so it can never keep
        holding the store's index.lock after we stop waiting for it."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *self.args,
            cwd=str(self.cwd) if self.cwd else None,
            env={**os.environ, **self.env} if self.env else None,
            stdin=asyncio.subprocess.PIPE if self.input is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        data = self.input.encode("utf-8") if isinstance(self.input, str) else self.input
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(data), timeout)
        except TimeoutError as e:
            await self._kill(proc)
            raise RuntimeError(f"git timed out after {timeout:.0f}s") from e
        except BaseException:
            await self._kill(proc)
            raise
        return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    @staticmethod
    async def _kill(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is None:
            proc.kill()
            await asyncio.shield(proc.wait())


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
            # `git --git-dir <store> --work-tree <ws> init` writes the repo directly
            # into the store dir; the workspace's own git is untouched.
            code, _out, err = await self._git(["init", "--quiet"]).run()
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
            exclude.parent.mkdir(parents=True, exist_ok=True)
            text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
            lines = [line.strip() for line in text.splitlines()]
            if ".openbot" not in lines:
                exclude.write_text(text.rstrip("\n") + "\n.openbot\n" if text else ".openbot\n", encoding="utf-8")
        except OSError as e:
            log.warning("could not write snapshot store exclude: %s", e)

    def _clear_stale_index_lock(self) -> None:
        """Remove an index.lock a killed git left behind; otherwise every later `git add`
        fails with "File exists" and snapshots stay off until someone deletes it by hand."""
        lock = self.store_dir / "index.lock"
        try:
            if time.time() - lock.stat().st_mtime > STALE_LOCK_SECONDS:
                lock.unlink()
                log.warning("removed stale snapshot index.lock in %s", self.store_dir)
        except FileNotFoundError:
            pass

    async def capture(self, *, pin: str | None = None) -> str | None:
        """Fingerprint the workspace tree.  None when the store could not be used
        (captures are best effort: a run must never fail because snapshots broke).

        `pin` (a run id) keeps the tree reachable from `refs/runs/<pin>` until `unpin`,
        so `gc --auto` never prunes the before-tree of a run parked on a human for weeks."""
        try:
            async with self._lock:
                await self._ensure_init()
                self._clear_stale_index_lock()
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
                if pin is not None:
                    code, _out, err = await self._git(["update-ref", f"refs/runs/{pin}", tree]).run()
                    if code != 0:
                        log.warning("snapshot pin failed for %s: %s", self.workspace_root, err.strip())
                log.debug("snapshot captured %s at %s", self.workspace_root, tree)
                return tree
        except (OSError, RuntimeError) as e:
            log.warning("snapshot capture failed for %s: %s", self.workspace_root, e)
            return None

    async def unpin(self, run_id: str) -> None:
        """Drop the ref `capture(pin=run_id)` made, letting gc reclaim the tree."""
        try:
            async with self._lock:
                code, _out, err = await self._git(["update-ref", "-d", f"refs/runs/{run_id}"]).run()
                if code != 0:
                    log.warning("snapshot unpin failed for %s: %s", self.workspace_root, err.strip())
        except (OSError, RuntimeError) as e:
            log.warning("snapshot unpin failed for %s: %s", self.workspace_root, e)

    async def diff(self, before: str, after: str) -> RunDiff | None:
        """Diff two captured trees, returning changed paths and the unified diff, or None
        when the trees could not be compared (never an empty diff that reads as "no changes").

        Renames are not detected (--no-renames), matching OpenCode: one run's
        delete+recreate of a file shows as delete+add, which is clearer in a
        per-run audit than a rename.
        """
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
                    return None
                parts = out.split("\0")
                changed: list[str] = []
                for i in range(0, len(parts) - 1, 2):
                    status = parts[i]
                    path = parts[i + 1] if i + 1 < len(parts) else ""
                    if not status or not path:
                        continue
                    if status[0] in ("A", "M", "D", "T"):  # T: type change, e.g. file -> symlink
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
                # Every capture writes a tree no ref points at; let git prune old loose
                # objects once they pile up (a no-op until git's auto thresholds are hit).
                code, _out, err = await self._git(["gc", "--auto", "--quiet"]).run()
                if code != 0:
                    log.warning("snapshot gc failed for %s: %s", self.workspace_root, err.strip())
                return RunDiff(changed_files=changed, diff=truncate_diff(out.rstrip("\n")))
        except (OSError, RuntimeError) as e:
            log.warning("snapshot diff failed for %s: %s", self.workspace_root, e)
            return None


def _workspace_root_for_thread(settings: Settings, thread) -> Path:
    """The resolved workspace root a run works in (same derivation as the runner)."""
    return thread_workspace_root(settings.workspace_root, thread.working_directory)


def store_for_run(settings: Settings, thread) -> SnapshotStore | None:
    """A ready-to-use SnapshotStore for a run's thread, or None when unsupported."""
    try:
        return SnapshotStore(settings, _workspace_root_for_thread(settings, thread))
    except (RuntimeError, ValueError):
        return None
