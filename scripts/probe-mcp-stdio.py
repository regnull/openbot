"""Opt-in stdio initialize/tools-list recorder; NOT an OS sandbox or tool-call test.

The launch JSON must name an independently verified sandbox launcher, not a naked
third-party executable. Stage packages as inert data first. See docs/mcp-catalog-results.md.
No packages are downloaded, installed, or launched by default.
"""
from __future__ import annotations

import argparse
import json
import os
import selectors
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def probe(launch: dict, timeout: float = 30) -> dict:
    """Record protocol traffic without calling any advertised tool (POSIX only)."""
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "launch": launch,
              "status": "blocked", "initialize": {"ok": False},
              "tools_list": {"ok": False, "names": []}, "tool_calls": "not-run", "events": []}
    events = result["events"]
    start = time.monotonic()
    process = subprocess.Popen(launch["argv"], cwd=launch["cwd"], env=launch["env"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stdin, stdout, stderr = process.stdin, process.stdout, process.stderr
    for stream, label in ((stdout, "stdout"), (stderr, "stderr")):
        selector.register(stream, selectors.EVENT_READ, label)
    pending = b""
    replies = {}

    def send(message):
        events.append({"direction": "send", "message": message})
        stdin.write((json.dumps(message) + "\n").encode())
        stdin.flush()

    def receive(request_id):
        nonlocal pending
        while request_id not in replies:
            if time.monotonic() - start > timeout:
                raise TimeoutError("startup/protocol deadline exceeded")
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                events.append({"direction": key.data, "text": chunk.decode(errors="replace")})
                if key.data != "stdout":
                    continue
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    message = json.loads(line)
                    if "id" in message and "method" not in message:
                        replies[message["id"]] = message
                    elif "id" in message:
                        send({"jsonrpc": "2.0", "id": message["id"], "error": {
                            "code": -32601, "message": "Client capability not supported"}})
            if request_id not in replies and not selector.get_map():
                raise RuntimeError(f"server streams closed (exit {process.poll()})")
        message = replies[request_id]
        if "error" in message:
            raise RuntimeError(str(message["error"]))
        return message["result"]

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "openbot-catalog-audit", "version": "1.0"}}})
        initialized = receive(1)
        result["initialize"] = {"ok": True, "response": initialized}
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        names, cursor = [], None
        for request_id in range(2, 102):
            send({"jsonrpc": "2.0", "id": request_id, "method": "tools/list",
                  "params": {"cursor": cursor} if cursor else {}})
            page = receive(request_id)
            names.extend(tool["name"] for tool in page["tools"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        if cursor or not names or len(names) != len(set(names)):
            raise ValueError("incomplete, empty or duplicate tool list")
        result["tools_list"] = {"ok": True, "names": names, "count": len(names)}
        result["status"] = "pass"
        result["startup_seconds"] = round(time.monotonic() - start, 3)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        result["blocker"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        # The launcher can exit while descendants still hold its pipes. Clean
        # the entire group before reading remaining output; never block on read().
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                break
        process.wait(timeout=3)
        for stream, label in ((stdout, "stdout"), (stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            remaining = stream.read()
            if remaining:
                events.append({"direction": label, "text": remaining.decode(errors="replace")})
            stream.close()
        selector.close()
        try:
            os.killpg(process.pid, 0)
            gone = False
        except ProcessLookupError:
            gone = True
        result["cleanup"] = {"exit_code": process.returncode, "process_group_gone": gone}
        if not gone:
            result.update(status="blocked", blocker="process group remained after cleanup")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-file", type=Path, required=True,
                        help="JSON with argv (sandbox launcher), cwd, and credential-free env")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--execute", action="store_true", help="explicitly authorize sandbox execution")
    args = parser.parse_args()
    if not args.execute:
        parser.error("execution requires --execute and an independently verified disposable sandbox")
    with args.output.open("x") as output:
        result = probe(json.loads(args.launch_file.read_text()), args.timeout)
        json.dump(result, output, indent=2)
        output.write("\n")
    print(json.dumps({key: result[key] for key in ("status", "tools_list", "cleanup")}))
    return int(result["status"] != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
