#!/usr/bin/env python3

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "electron-dev.sh"


def run_launcher(*args, include_details=False):
    env = {**os.environ, "ELECTRON_DEV_PRINT_ARGS": "1"}
    if include_details:
        env["OPENBOT_INCLUDE_LLM_CALL_DETAILS"] = "true"
    return subprocess.run(
        ["bash", str(SCRIPT), *args], text=True, capture_output=True, env=env, check=False
    )


def test_electron_launcher_excludes_details_and_omits_root_by_default():
    result = run_launcher()
    assert result.returncode == 0, result.stderr
    assert result.stdout == "DETAILS_FLAG=--exclude-llm-call-details\nROOT_ARGS=\n"


def test_electron_launcher_forwards_explicit_detail_opt_in():
    result = run_launcher("--include-llm-call-details")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "DETAILS_FLAG=--include-llm-call-details\nROOT_ARGS=\n"


def test_electron_launcher_forwards_root_argument_with_spaces():
    result = run_launcher("--root-directory", "/tmp/root with spaces")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "DETAILS_FLAG=--exclude-llm-call-details\nROOT_ARGS=--root-directory|/tmp/root with spaces|\n"


def test_electron_launcher_accepts_legacy_positional_root():
    result = run_launcher("/tmp/legacy root")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "DETAILS_FLAG=--exclude-llm-call-details\nROOT_ARGS=--root-directory|/tmp/legacy root|\n"


def test_electron_launcher_rejects_missing_root_value():
    result = run_launcher("--root-directory")
    assert result.returncode == 2
    assert "requires a directory" in result.stderr
