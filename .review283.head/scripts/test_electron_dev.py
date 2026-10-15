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


def print_ports(**env):
    return subprocess.run(
        ["bash", str(SCRIPT)], text=True, capture_output=True, check=False,
        env={**{k: v for k, v in os.environ.items() if k not in ("ELECTRON_BACKEND_PORT", "FRONTEND_PORT")},
             "ELECTRON_DEV_PRINT_PORTS": "1", **env},
    )


def hold(port):
    """Listen on `port` unless something (e.g. a running OpenBot) already does; either way it is taken."""
    import socket

    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        s.listen()
    except OSError:
        s.close()
        return None
    return s


def test_electron_launcher_skips_ports_another_instance_holds():
    held = [hold(8001), hold(5173)]
    try:
        result = print_ports()
    finally:
        for s in held:
            if s:
                s.close()
    assert result.returncode == 0, result.stderr
    backend = int(result.stdout.split("ELECTRON_BACKEND_PORT=")[1].split()[0])
    frontend = int(result.stdout.split("FRONTEND_PORT=")[1].split()[0])
    assert backend > 8001 and frontend > 5173 and backend != frontend


def test_electron_launcher_rejects_an_explicit_port_in_use():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        result = print_ports(ELECTRON_BACKEND_PORT=str(s.getsockname()[1]))
    assert result.returncode == 1 and "already in use" in result.stderr
