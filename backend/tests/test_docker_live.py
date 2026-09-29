"""The Docker setup (Dockerfile, compose.yaml) against the real backend image.

Opt-in (`uv run pytest -m docker`): builds the image and starts a container. The tools are run
inside the container the same way the backend runs them: as root, on uvloop (which uvicorn uses
and whose subprocess support differs from asyncio's), with SHELL_USER=shell.
"""
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO = Path(__file__).resolve().parents[2]
IMAGE = "openbot-backend:test"
API_KEY = "test-key-for-docker-checks"

# Runs one tool call inside the container: argv = shell_user tool arg [content or timeout]
TOOL = """
import sys
from pathlib import Path
import uvloop
from langchain.tools import ToolRuntime
from openbot.tools.builtin.files import write_file
from openbot.tools.builtin.shell import run_shell
from openbot.tools.context import RunContext

user, tool, arg = sys.argv[1], sys.argv[2], sys.argv[3]
ctx = RunContext("b", "bot", "Bot", "t", "r", Path("/workspace"), None, shell_user=user or None)
rt = ToolRuntime(context=ctx, store=None, state={}, tool_call_id="c", config={}, stream_writer=lambda *_: None)
if tool == "write_file":
    print(uvloop.run(write_file.ainvoke({"path": arg, "content": sys.argv[4], "runtime": rt})))
else:
    timeout = int(sys.argv[4]) if len(sys.argv) > 4 else 120
    print(uvloop.run(run_shell.ainvoke({"command": arg, "timeout": timeout, "runtime": rt})))
"""


def docker(*args, check=True, input=None):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, input=input)


@pytest.fixture(scope="module")
def container():
    if shutil.which("docker") is None or docker("info", check=False).returncode != 0:
        pytest.skip("Docker is not available")
    docker("build", "-q", "-t", IMAGE, str(REPO))
    cid = docker("run", "-d", "-p", "127.0.0.1::8000",
                 "-e", "SHELL_USER=shell", "-e", f"OPENBOT_API_KEY={API_KEY}",
                 "-e", "OPENAI_API_KEY=sk-sentinel", IMAGE).stdout.strip()
    try:
        port = docker("port", cid, "8000/tcp").stdout.strip().rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                if urllib.request.urlopen(f"{base}/api/v1/health", timeout=2).status == 200:
                    break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.5)
        else:
            pytest.fail("backend did not become healthy:\n" + docker("logs", cid, check=False).stdout)
        # Store a provider key through the API, as the settings page would: this creates secret.key.
        req = urllib.request.Request(f"{base}/api/v1/settings", method="PATCH",
                                     data=b'{"openai_api_key": "sk-stored-sentinel"}',
                                     headers={"X-API-Key": API_KEY, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        yield cid, base
    finally:
        docker("rm", "-f", cid, check=False)


def tool(cid, *args, user="shell"):
    # `docker exec` skips the entrypoint, so apply the backend's umask here (checked below).
    return docker("exec", "-i", cid, "sh", "-c", 'umask 002 && exec /app/backend/.venv/bin/python - "$@"', "sh",
                  user, *args, input=TOOL).stdout


def backend_pid(cid):
    return docker("exec", cid, "pgrep", "-f", "openbot.cli").stdout.split()[0]


def test_tini_is_pid_1_and_the_backend_has_a_shared_umask(container):
    cid, _ = container
    assert "tini" in docker("exec", cid, "cat", "/proc/1/cmdline").stdout
    assert "Umask:\t0002" in docker("exec", cid, "cat", f"/proc/{backend_pid(cid)}/status").stdout


def test_health_and_api_key(container):
    _, base = container
    assert urllib.request.urlopen(f"{base}/api/v1/health").status == 200
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"{base}/api/v1/settings")
    assert e.value.code == 401


def test_shell_runs_as_the_shell_user_without_the_server_env(container):
    cid, _ = container
    out = tool(cid, "run_shell", "id -un; env")
    assert "shell" in out
    assert "sk-sentinel" not in out and API_KEY not in out


def test_shell_cannot_read_state_keys_or_the_backend_env(container):
    cid, _ = container
    out = tool(cid, "run_shell", f"cat /data/openbot.db; cat /data/secret.key; cat /proc/{backend_pid(cid)}/environ")
    assert out.count("Permission denied") == 3
    assert "sk-stored-sentinel" not in out and "sk-sentinel" not in out


def test_shell_cannot_use_the_api_on_localhost(container):
    cid, _ = container
    out = tool(cid, "run_shell", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v1/settings")
    assert "401" in out


def test_backend_and_shell_can_edit_each_others_files(container):
    cid, _ = container
    assert "error" not in tool(cid, "write_file", "shared/notes.txt", "from the backend\n")
    out = tool(cid, "run_shell", "echo from the shell >> shared/notes.txt && mkdir -p made && echo x > made/f && cat shared/notes.txt")
    assert "exit code: 0" in out and "from the shell" in out
    assert "error" not in tool(cid, "write_file", "made/f", "overwritten by the backend\n")
    assert "exit code: 0" in tool(cid, "run_shell", "echo again >> made/f")


def test_shell_can_use_git_and_a_venv(container):
    cid, _ = container
    out = tool(cid, "run_shell",
               "mkdir -p repo && cd repo && git init -q && git config user.email a@b.c && git config user.name a"
               " && touch f && git add f && git commit -qm init && python3 -m venv .venv && .venv/bin/pip --version")
    assert "exit code: 0" in out and "pip " in out


def test_setuid_programs_cannot_get_back_to_root(container):
    cid, _ = container
    out = tool(cid, "run_shell", "grep -E '^(CapEff|NoNewPrivs)' /proc/self/status; su -c id root </dev/null")
    assert "CapEff:\t0000000000000000" in out and "NoNewPrivs:\t1" in out
    assert "uid=0" not in out


def test_timeout_kills_the_shell_users_whole_command_tree(container):
    # The backend (root) kills the process group; setpriv execs bash in place, so the group is the
    # shell user's command and everything it started.
    cid, _ = container
    start = time.monotonic()
    out = tool(cid, "run_shell", "sleep 30 & echo $! > bg.pid; sleep 30", "2")
    assert "timed out" in out
    assert time.monotonic() - start < 15
    alive = docker("exec", cid, "sh", "-c", "kill -0 $(cat /workspace/bg.pid) 2>/dev/null && echo alive || echo gone")
    assert alive.stdout.strip() == "gone"
    # ...and reaped, not left as a zombie under PID 1.
    assert " Z" not in docker("exec", cid, "ps", "-eo", "pid,stat").stdout


def test_unknown_shell_user_fails_closed(container):
    cid, _ = container
    out = tool(cid, "run_shell", "touch ran", user="no-such-user")
    assert out.strip().startswith("error:")
    assert "No such file" in tool(cid, "run_shell", "ls ran")


def test_shell_user_without_api_key_refuses_to_start():
    if shutil.which("docker") is None or docker("info", check=False).returncode != 0:
        pytest.skip("Docker is not available")
    docker("build", "-q", "-t", IMAGE, str(REPO))
    run = subprocess.run(["docker", "run", "--rm", "-e", "SHELL_USER=shell", IMAGE],
                         capture_output=True, text=True, timeout=60, check=False)
    assert run.returncode != 0
    assert "SHELL_USER needs OPENBOT_API_KEY" in run.stdout + run.stderr
