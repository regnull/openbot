"""Per-run workspace snapshot tests: the SnapshotStore git tricks, plus the runner wiring that
attaches changed_files/diff to a finished run."""

import asyncio
import os
from pathlib import Path

import pytest

from openbot.api.schemas import RunDetail, RunOut
from openbot.config import Settings
from openbot.db.models import Run
from openbot.runtime.snapshot import (
    RunWindows,
    SnapshotStore,
    snapshot_store_dir,
    store_for_run,
    truncate_diff,
)
from tests.fakes import ai, call
from tests.test_runner import get, make


def make_settings(tmp_path: Path, *, root: bool = True) -> Settings:
    kwargs = {
        "database_url": f"sqlite+aiosqlite:///{tmp_path}/test.db",
        "workspace_root": tmp_path / "workspace",
        "tools_dir": tmp_path / "tools",
        "log_file": tmp_path / "logs" / "openbot.log",
        "seed_demo_bots": False,
        "memory_reflection_delay": 0.01,
        "mcp_config": tmp_path / "mcp.json",
        "mcp_token_key_file": tmp_path / "mcp_token.key",
        "secret_key_file": tmp_path / "secret.key",
        "webhook_retry_delays": [0.01, 0.01, 0.01],
        "_env_file": None,
    }
    if root:
        kwargs["OPENBOT_ROOT_DIRECTORY"] = tmp_path / "root"
    return Settings(**kwargs)


class FakeThread:
    working_directory: str | None = None


@pytest.mark.asyncio
async def test_store_for_run_needs_a_state_dir(tmp_path, monkeypatch):
    """Without a root directory there is no state dir, so snapshots are off and store_for_run
    returns None instead of raising."""
    monkeypatch.delenv("OPENBOT_ROOT_DIRECTORY", raising=False)
    settings = make_settings(tmp_path, root=False)
    assert settings.state_dir is None
    assert snapshot_store_dir(settings, settings.workspace_root) is None
    assert store_for_run(settings, FakeThread()) is None


@pytest.mark.asyncio
async def test_snapshot_store_captures_and_diffs_changes(tmp_path):
    settings = make_settings(tmp_path)
    ws = settings.workspace_root
    ws.mkdir(parents=True)
    (ws / "keep.txt").write_text("before\n", encoding="utf-8")

    store = SnapshotStore(settings, ws)
    before = await store.capture()
    assert before

    (ws / "keep.txt").write_text("before\nchanged\n", encoding="utf-8")
    (ws / "new.txt").write_text("hello\n", encoding="utf-8")
    (ws / "gone.txt").write_text("bye\n", encoding="utf-8")
    (ws / "gone.txt").unlink()

    after = await store.capture()
    rd = await store.diff(before, after)
    assert rd.changed_files == ["keep.txt", "new.txt"]
    assert "keep.txt" in rd.diff and "+changed" in rd.diff
    assert "+hello" in rd.diff
    assert "gone.txt" not in rd.changed_files  # deleted before 'after', never entered the tree


@pytest.mark.asyncio
async def test_snapshot_store_reports_deletions_between_captures(tmp_path):
    settings = make_settings(tmp_path)
    ws = settings.workspace_root
    ws.mkdir(parents=True)
    (ws / "a.txt").write_text("x\n", encoding="utf-8")

    store = SnapshotStore(settings, ws)
    before = await store.capture()
    (ws / "a.txt").unlink()
    after = await store.capture()
    rd = await store.diff(before, after)
    assert rd.changed_files == ["a.txt"]


@pytest.mark.asyncio
async def test_snapshot_store_excludes_openbot_state_and_gitignored(tmp_path):
    settings = make_settings(tmp_path)
    ws = settings.workspace_root
    ws.mkdir(parents=True)
    (ws / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (ws / "tracked.txt").write_text("t\n", encoding="utf-8")

    store = SnapshotStore(settings, ws)
    before = await store.capture()
    (ws / "ignored.txt").write_text("nope\n", encoding="utf-8")
    (ws / ".openbot").mkdir(exist_ok=True)
    (ws / ".openbot" / "state.txt").write_text("secret\n", encoding="utf-8")
    (ws / "tracked.txt").write_text("t2\n", encoding="utf-8")
    after = await store.capture()
    rd = await store.diff(before, after)
    assert rd.changed_files == ["tracked.txt"]
    assert ".openbot" not in rd.diff and "ignored.txt" not in rd.diff


@pytest.mark.asyncio
async def test_no_changes_produces_empty_diff(tmp_path):
    settings = make_settings(tmp_path)
    ws = settings.workspace_root
    ws.mkdir(parents=True)
    store = SnapshotStore(settings, ws)
    before = await store.capture()
    after = await store.capture()
    rd = await store.diff(before, after)
    assert rd.changed_files == [] and rd.diff == ""


@pytest.mark.asyncio
async def test_runner_attaches_changed_files_and_diff_to_a_completed_run(tmp_path):
    from tests.fakes import ScriptedChatModel

    ScriptedChatModel.seen.clear()
    settings = make_settings(tmp_path)
    settings.workspace_root.mkdir(parents=True)
    (settings.workspace_root / "seed.txt").write_text("seed\n", encoding="utf-8")
    services, _eng, _t, run = await make(
        settings,
        {"eng": [ai(tool_calls=[call("run_shell", command="echo hi > note.txt")]), ai("done")]},
        tool_names=["run_shell"],
    )
    await services.runner.execute(run.id)
    await services.runner.wait_snapshots()
    run = await get(services, Run, run.id)
    assert run.status == "completed"
    assert run.changed_files == ["note.txt"]
    assert "+hi" in (run.diff or "")
    assert "seed.txt" not in (run.changed_files or [])


@pytest.mark.asyncio
async def test_runs_without_changes_store_empty_lists(tmp_path):
    settings = make_settings(tmp_path)
    settings.workspace_root.mkdir(parents=True)
    services, _eng, _t, run = await make(
        settings,
        {"eng": [ai("no tools, just a reply")]},
    )
    await services.runner.execute(run.id)
    await services.runner.wait_snapshots()
    run = await get(services, Run, run.id)
    assert run.status == "completed"
    assert run.changed_files == [] and run.diff == ""
    assert run.changes_shared is False


def test_truncate_diff_cuts_at_a_line_and_says_so():
    diff = "".join(f"+line {i}\n" for i in range(1000))
    assert truncate_diff(diff, limit=len(diff)) == diff
    out = truncate_diff(diff, limit=100)
    head, marker = out.rsplit("\n", 1)
    assert len(head) <= 100 and head.endswith(tuple(f"+line {i}" for i in range(20)))
    assert marker.startswith("... diff truncated") and f"{len(diff):,}" in marker


def test_run_windows_flag_overlapping_runs_only(tmp_path):
    ws, other_ws = tmp_path / "ws", tmp_path / "other"
    w = RunWindows()
    w.open(ws, "a")
    assert w.close(ws, "a") is False  # alone
    w.open(ws, "a")
    w.open(other_ws, "x")  # a sibling workspace never overlaps
    w.open(ws, "b")  # starts while a is active: both are shared
    assert w.close(ws, "a") is True
    w.open(ws, "c")  # starts after a ended, while b is still active
    assert w.close(ws, "b") is True
    assert w.close(ws, "c") is True
    w.open(ws, "d")  # everyone gone: d is alone again
    assert w.close(ws, "d") is False
    assert w.close(other_ws, "x") is False


def test_run_windows_treat_nested_roots_as_overlapping(tmp_path):
    """A thread working in sub/ edits files a thread working at the root snapshots."""
    w = RunWindows()
    w.open(tmp_path / "ws", "root-run")
    w.open(tmp_path / "ws" / "sub", "sub-run")
    assert w.close(tmp_path / "ws" / "sub", "sub-run") is True
    assert w.close(tmp_path / "ws", "root-run") is True


def test_run_list_schema_leaves_the_diff_to_run_detail():
    """Thread loads list every run; the diff (possibly large) is only served by the run detail."""
    assert "diff" not in RunOut.model_fields and "changed_files" in RunOut.model_fields
    assert "diff" in RunDetail.model_fields


@pytest.mark.asyncio
async def test_status_is_recorded_before_the_snapshot_finishes(tmp_path):
    """The run's terminal status must not wait on git: the diff is attached afterwards."""
    settings = make_settings(tmp_path)
    settings.workspace_root.mkdir(parents=True)
    services, _eng, _t, run = await make(settings, {"eng": [ai("done")]})
    gate = asyncio.Event()
    real_finish = services.runner._snapshot_finish

    async def slow_finish(*args):
        await gate.wait()
        await real_finish(*args)

    services.runner._snapshot_finish = slow_finish
    await services.runner.execute(run.id)
    row = await get(services, Run, run.id)
    assert row.status == "completed" and row.changed_files is None  # ended, diff still pending
    gate.set()
    await services.runner.wait_snapshots()
    row = await get(services, Run, run.id)
    assert row.changed_files == []


@pytest.mark.asyncio
async def test_concurrent_runs_in_one_workspace_are_flagged_shared(tmp_path):
    settings = make_settings(tmp_path)
    settings.workspace_root.mkdir(parents=True)
    services, _eng, thread, run = await make(settings, {"eng": [ai("done")]})
    # Another run is active in the same workspace while this one works.
    services.runner._snapshot_windows.open(store_for_run(settings, thread).workspace_root, "other-run")
    await services.runner.execute(run.id)
    await services.runner.wait_snapshots()
    row = await get(services, Run, run.id)
    assert row.status == "completed" and row.changes_shared is True


@pytest.mark.asyncio
async def test_cancelling_a_run_parked_on_a_human_closes_its_window(tmp_path):
    """A run waiting on a human ends in cancel_run, outside execute(): its window must close,
    or every later run in that workspace would be flagged as shared."""
    settings = make_settings(tmp_path)
    settings.workspace_root.mkdir(parents=True)
    services, _eng, thread, run = await make(settings, {"eng": [ai("done")]})
    await services.runner._snapshot_capture_before(run.id, thread)
    root = store_for_run(settings, thread).workspace_root
    async with services.session_factory() as session:
        row = await session.get(Run, run.id)
        row.status = "waiting_human"
        await session.commit()
    from openbot.runtime.actors import ActorSystem

    services.actors = ActorSystem(services, 1)
    assert await services.actors.cancel_run(run.id)
    await services.runner.wait_snapshots()
    assert run.id not in services.runner._snapshot_before
    assert services.runner._snapshot_windows.close(root, "probe") is False
    row = await get(services, Run, run.id)
    assert row.status == "cancelled" and row.changed_files == []


@pytest.mark.asyncio
async def test_a_run_that_crashes_before_its_try_block_still_closes_its_window(tmp_path, monkeypatch):
    """execute() can leave from any await (an exception, a cancel); a run with a before-tree
    must still get its snapshot finished, or later runs in the workspace read as shared."""
    settings = make_settings(tmp_path)
    settings.workspace_root.mkdir(parents=True)
    services, _eng, thread, run = await make(settings, {"eng": [ai("done")]})
    runner = services.runner
    await runner._snapshot_capture_before(run.id, thread)  # as if a first segment had run

    async def boom(*_a, **_k):
        raise RuntimeError("db went away")

    monkeypatch.setattr(runner, "_next_seq", boom)
    with pytest.raises(RuntimeError):
        await runner.execute(run.id)
    await runner.wait_snapshots()
    assert run.id not in runner._snapshot_before
    assert runner._snapshot_windows.close(store_for_run(settings, thread).workspace_root, "probe") is False


@pytest.mark.asyncio
async def test_pinned_before_tree_survives_until_unpinned(tmp_path):
    settings = make_settings(tmp_path)
    ws = settings.workspace_root
    ws.mkdir(parents=True)
    (ws / "a.txt").write_text("x\n", encoding="utf-8")
    store = SnapshotStore(settings, ws)
    tree = await store.capture(pin="run-1")
    ref = store.store_dir / "refs" / "runs" / "run-1"
    assert ref.read_text().strip() == tree
    await store.unpin("run-1")
    assert not ref.exists()


@pytest.mark.asyncio
async def test_a_stale_index_lock_does_not_disable_snapshots(tmp_path):
    settings = make_settings(tmp_path)
    ws = settings.workspace_root
    ws.mkdir(parents=True)
    store = SnapshotStore(settings, ws)
    assert await store.capture()
    lock = store.store_dir / "index.lock"
    lock.write_text("", encoding="utf-8")
    old = lock.stat().st_mtime - 3600
    os.utime(lock, (old, old))  # left behind by a git killed an hour ago
    (ws / "b.txt").write_text("y\n", encoding="utf-8")
    assert await store.capture()
    assert not lock.exists()


@pytest.mark.asyncio
async def test_an_uncomparable_tree_gives_no_diff_rather_than_no_changes(tmp_path):
    settings = make_settings(tmp_path)
    ws = settings.workspace_root
    ws.mkdir(parents=True)
    store = SnapshotStore(settings, ws)
    after = await store.capture()
    assert await store.diff("0" * 40, after) is None
