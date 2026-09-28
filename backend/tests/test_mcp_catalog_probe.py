"""Synthetic stdio client regressions; these are NOT catalog handshake evidence."""
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/probe-mcp-stdio.py"
probe = runpy.run_path(str(SCRIPT))["probe"]
STUB = '''import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request['method'] == 'initialize':
        result = {'protocolVersion': '2025-11-25', 'serverInfo': {'name': 'synthetic', 'version': '1'}, 'capabilities': {}}
    elif request['method'] == 'tools/list':
        if request['params'].get('cursor'):
            result = {'tools': [{'name': 'second'}]}
        else:
            result = {'tools': [{'name': 'first'}], 'nextCursor': 'page2'}
    else:
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
'''


def launch(tmp_path, source):
    return {"argv": [sys.executable, "-u", "-c", source], "cwd": str(tmp_path), "env": {}}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group probe")
def test_probe_records_initialize_pagination_and_cleanup(tmp_path):
    result = probe(launch(tmp_path, STUB), timeout=5)
    assert result["status"] == "pass"
    assert result["initialize"]["response"]["serverInfo"]["name"] == "synthetic"
    assert result["tools_list"] == {"ok": True, "names": ["first", "second"], "count": 2}
    assert result["cleanup"]["process_group_gone"]
    assert result["tool_calls"] == "not-run"
    assert all(event.get("message", {}).get("method") != "tools/call" for event in result["events"])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group probe")
@pytest.mark.parametrize("source", ["print('not-json', flush=True)", "raise SystemExit(1)", "import time; time.sleep(10)"])
def test_probe_failures_are_not_passes(tmp_path, source):
    result = probe(launch(tmp_path, source), timeout=0.1)
    assert result["status"] == "blocked" and result["blocker"]
    assert not result["tools_list"]["ok"]
    assert result["cleanup"]["process_group_gone"]


def test_cli_never_executes_without_opt_in(tmp_path):
    config = tmp_path / "launch.json"
    config.write_text(json.dumps(launch(tmp_path, "raise AssertionError('must not execute')")))
    output = tmp_path / "output.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--launch-file", str(config), "--output", str(output)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "execution requires --execute" in result.stderr
    assert not output.exists()
