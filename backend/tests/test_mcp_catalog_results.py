"""Offline integrity checks for historical receipts, not a fresh runtime test."""
import hashlib
import json
from pathlib import Path

from openbot.mcp.catalog import CATALOG_BY_ID

DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_versioned_matrix_is_complete_and_honest():
    matrix = json.loads((DOCS / "mcp-catalog-results.json").read_text())
    rows = matrix["entries"]
    by_id = {row["id"]: row for row in rows}
    assert len(rows) == len(by_id) == 35
    assert set(by_id) == set(CATALOG_BY_ID)
    assert matrix["summary"]["protocol_pass"] == sum(row["status"] == "pass" for row in rows)
    assert matrix["summary"]["blocked_unrun"] == sum(row["status"] == "blocked" and not row["initialize"]["ok"] for row in rows)
    assert matrix["summary"]["incomplete_identity"] == 1
    assert sum(row["original_no_declared_credentials"] for row in rows) == 15
    assert all(by_id[key]["status"] == "pass" for key in ("filesystem", "git", "memory", "sequential-thinking", "time", "fetch"))
    text = (DOCS / "mcp-catalog-results.md").read_text()
    for row in rows:
        assert f"| {row['id']} |" in text
        assert row["package_metadata"]["source"] and row["package_metadata"]["provenance"]
        assert row["tool_calls"] == "not-run"
        if row["status"] == "blocked":
            assert row["blocker"]
        if not row["initialize"]["ok"]:
            assert row["status"] == "blocked" and not row["tools_list"]["ok"]
            continue
        assert row["initialize"]["ok"] and row["tools_list"]["ok"]
        assert row["tools_list"]["count"] == len(row["tools_list"]["names"]) > 0
        assert row["cleanup"]["process_group_gone"]
        path = DOCS / row["evidence_log"]
        assert path.resolve().is_relative_to(DOCS.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["evidence_sha256"]
        receipt = json.loads(path.read_text())["receipt"]
        assert receipt["initialize"] == row["initialize"]
        assert receipt["tools_list"] == row["tools_list"]
        assert receipt["sandbox_probe"]["outbound"] not in ("ALLOWED", "VISIBLE")
    # Preserve the empty upstream value; neither fabricate a version nor hide
    # successful protocol stages to satisfy a stricter identity requirement.
    assert by_id["aws"]["status"] == "blocked"
    assert by_id["aws"]["initialize"]["response"]["serverInfo"]["version"] == ""
    assert by_id["aws"]["initialize"]["ok"] and by_id["aws"]["tools_list"]["ok"]


def test_sqlite_failure_and_constraint_evidence_are_retained():
    rows = json.loads((DOCS / "mcp-catalog-results.json").read_text())["entries"]
    sqlite = next(row for row in rows if row["id"] == "sqlite")
    assert sqlite["catalog_status"] == "deprecated"  # a protocol pass is not maintenance
    assert sqlite["current_catalog_argv"] == ["uvx", *CATALOG_BY_ID["sqlite"]["args"]]
    assert sqlite["launch_argv"][1:3] == ["tool", "run"]
    assert "mcp<2" in sqlite["launch_argv"]
    failure = json.loads((DOCS / "mcp-catalog-evidence/sqlite-incompatible.json").read_text())
    assert failure["receipt"]["status"] == "blocked"
    assert "list_resources" in "".join(event.get("text", "") for event in failure["events"])
