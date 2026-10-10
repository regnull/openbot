"""Stands in for the `claude` CLI in tests, so CI needs no install and no account.

FAKE_CLAUDE_DIR holds script.json, a list with one step per invocation (the last one repeats):
  {"lines": [...stream-json lines...], "stderr": "...", "exit": 0, "hang": false}
Each call appends its argv, cwd, stdin, system prompt file content and environment names to calls.jsonl.
A hanging step starts a child that sleeps too and writes both pids to pids.txt, for the cancel tests.
A step with "leave_child" starts such a child, which inherits stdout and stderr, and then ends normally.
`--version` answers with FAKE_CLAUDE_VERSION (default a current version) and is not a call.
`auth status` exits with the code in FAKE_CLAUDE_DIR/auth_exit.txt (default 0); not a call either.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

home = Path(os.environ["FAKE_CLAUDE_DIR"])
if sys.argv[1:] == ["--version"]:
    # Each call is counted in versions.txt.
    with (home / "versions.txt").open("a", encoding="utf-8") as f:
        f.write("x")
    print(os.environ.get("FAKE_CLAUDE_VERSION", "2.1.283 (Claude Code)"), flush=True)
    sys.exit(0)
if sys.argv[1:] == ["auth", "status"]:
    exit_file = home / "auth_exit.txt"
    code = int(exit_file.read_text().strip()) if exit_file.is_file() else 0
    print(json.dumps({"loggedIn": code == 0}), flush=True)
    sys.exit(code)
calls = home / "calls.jsonl"
done = len(calls.read_text(encoding="utf-8").splitlines()) if calls.exists() else 0
steps = json.loads((home / "script.json").read_text(encoding="utf-8"))
step = steps[min(done, len(steps) - 1)]
argv = sys.argv[1:]
prompt = sys.stdin.buffer.read().decode("utf-8")
system_prompt = ""
if "--append-system-prompt-file" in argv:
    system_prompt = Path(argv[argv.index("--append-system-prompt-file") + 1]).read_text(encoding="utf-8")
with calls.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "stdin": prompt, "system_prompt": system_prompt,
                        "env": sorted(os.environ)}) + "\n")
# Bytes, as the real CLI writes UTF-8 whatever the console code page is.
for line in step.get("lines", []):
    sys.stdout.buffer.write(line.rstrip("\n").encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
if step.get("stderr"):
    sys.stderr.write(step["stderr"])
    sys.stderr.flush()
if step.get("leave_child"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    (home / "pids.txt").write_text(f"{os.getpid()} {child.pid}", encoding="utf-8")
if step.get("hang"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    (home / "pids.txt").write_text(f"{os.getpid()} {child.pid}", encoding="utf-8")
    time.sleep(600)
sys.exit(step.get("exit", 0))
