"""Per-run workspace snapshot tests: the SnapshotStore git tricks, plus the runner wiring that
attaches changed_files/diff to a finished run."""

from pathlib import Path

import pytest

from openbot.config import Settings
from openbot.db.models import Run
from openbot.runtime.snapshot import SnapshotStore, snapshot_store_dir, store_for_run
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
    run = await get(services, Run, run.id)
    assert run.status == "completed"
    assert run.changed_files == [] and run.diff == ""