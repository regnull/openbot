#!/usr/bin/env bash
# Launch the Electron development app with its own backend and Vite server.
set -Eeuo pipefail

# Resolve every repository-relative command and path from this script, rather than the caller's
# working directory. This keeps `make electron` usable from an arbitrary directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd -- "$REPO_ROOT"

# This deterministic probe is used by regression tests without starting child services.
if [[ "${ELECTRON_DEV_PRINT_PATHS:-}" == "1" ]]; then
  printf 'REPO_ROOT=%s\n' "$REPO_ROOT"
  exit 0
fi

# True when nothing on this machine is listening on the port (IPv4 or IPv6 loopback), so a second
# OpenBot instance can tell the first one's ports are taken.
port_is_free() {
  python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        continue                        # no IPv6 on this host
    try:
        s.bind((host, port))
    except OSError as e:
        if family == socket.AF_INET6 and e.errno == 49:   # EADDRNOTAVAIL: ::1 not configured
            continue
        sys.exit(1)
    finally:
        s.close()
PY
}

# First free port from $1 upward, skipping $2 (the port already chosen for the other server).
first_free_port() {
  local port="$1"
  for _ in {1..100}; do
    if [[ "$port" != "${2:-}" ]] && port_is_free "$port"; then
      printf '%s' "$port"
      return 0
    fi
    port=$((port + 1))
  done
  echo "No free port found from $1 upward" >&2
  return 1
}

# Ports default to the first free ones from 8001 and 5173, so a second instance (with its own
# DATABASE_URL) starts beside the first instead of attaching to its backend and UI. An explicitly
# set port is used as given, and fails below if it is taken.
if [[ -z "${ELECTRON_BACKEND_PORT:-}" ]]; then
  ELECTRON_BACKEND_PORT="$(first_free_port 8001)"
fi
if [[ -z "${FRONTEND_PORT:-}" ]]; then
  FRONTEND_PORT="$(first_free_port 5173 "$ELECTRON_BACKEND_PORT")"
fi
for port in "$ELECTRON_BACKEND_PORT" "$FRONTEND_PORT"; do
  port_is_free "$port" || { echo "Port $port is already in use; set ELECTRON_BACKEND_PORT / FRONTEND_PORT to free ports" >&2; exit 1; }
done
if [[ "${ELECTRON_DEV_PRINT_PORTS:-}" == "1" ]]; then
  printf 'ELECTRON_BACKEND_PORT=%s\nFRONTEND_PORT=%s\n' "$ELECTRON_BACKEND_PORT" "$FRONTEND_PORT"
  exit 0
fi
DETAILS_FLAG="--exclude-llm-call-details"
if [[ "${OPENBOT_INCLUDE_LLM_CALL_DETAILS:-false}" == "true" ]]; then
  DETAILS_FLAG="--include-llm-call-details"
fi
if [[ "${1:-}" == "--include-llm-call-details" ]]; then
  DETAILS_FLAG="--include-llm-call-details"
  shift
fi
ROOT_ARGS=()
if [[ "${1:-}" == "--root-directory" ]]; then
  [[ -n "${2:-}" ]] || { echo "--root-directory requires a directory" >&2; exit 2; }
  ROOT_ARGS+=(--root-directory "$2")
  shift 2
elif [[ -n "${1:-}" ]]; then
  # Preserve compatibility with direct callers that pass the root as the first
  # argument, while accepting the explicit form emitted by `make electron`.
  ROOT_ARGS+=(--root-directory "$1")
  shift
fi
[[ -z "${1:-}" ]] || { echo "unexpected Electron launcher argument: $1" >&2; exit 2; }
if [[ "${ELECTRON_DEV_PRINT_ARGS:-}" == "1" ]]; then
  printf 'DETAILS_FLAG=%s\n' "$DETAILS_FLAG"
  printf 'ROOT_ARGS='
  if ((${#ROOT_ARGS[@]})); then
    printf '%s|' "${ROOT_ARGS[@]}"
  fi
  printf '\n'
  exit 0
fi
BACKEND_URL="http://localhost:${ELECTRON_BACKEND_PORT}"
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"

backend_pid=""
frontend_pid=""
kill_process_group() {
  local pid="$1"
  [[ -z "$pid" ]] && return 0

  # Backend and Vite each create children. Kill the process group so those children do not
  # outlive the launcher, then escalate if necessary.
  kill -TERM -- "-${pid}" 2>/dev/null || true
  for _ in {1..20}; do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -KILL -- "-${pid}" 2>/dev/null || true
}

cleanup() {
  trap - EXIT INT TERM
  kill_process_group "$frontend_pid"
  kill_process_group "$backend_pid"
  wait "$frontend_pid" "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Linux provides setsid, but it is not available on a standard macOS install.
# Use Python's os.setsid fallback there so the launcher remains portable while
# retaining a dedicated process group for uvicorn/Vite and their children.
run_in_process_group() {
  # exec (rather than run-and-wait) so this backgrounded function's own subshell PID -- what
  # the caller captures as $! -- becomes setsid's PID, which setsid then turns into the new
  # group's PGID. Without exec, $! would name this subshell instead: it shares the launcher's
  # own process group, so `kill -TERM -- "-$pid"` in kill_process_group would target an empty
  # group and silently leave uvicorn/Vite running.
  if command -v setsid >/dev/null 2>&1; then
    exec setsid "$@"
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    echo "The Electron launcher requires setsid or python3 to manage child processes." >&2
    return 1
  fi
  exec python3 - "$@" <<'PY'
import os
import sys

os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
PY
}

# Use the same root-relative commands as the Makefile targets. Electron intentionally runs
# without backend reload or Vite file watching: changes take effect after an app restart,
# avoiding watcher activity that can freeze the UI while messages are being sent.
echo "Starting Electron backend on ${BACKEND_URL}"
run_in_process_group uv run --project backend python -m openbot.cli "$DETAILS_FLAG" ${ROOT_ARGS[@]+"${ROOT_ARGS[@]}"} --port "$ELECTRON_BACKEND_PORT" &
backend_pid=$!

echo "Starting Vite frontend on ${FRONTEND_URL}"
run_in_process_group env FRONTEND_PORT="$FRONTEND_PORT" VITE_BACKEND_PORT="$ELECTRON_BACKEND_PORT" ELECTRON_DEV="1" bash -c '
  cd frontend
  pnpm dev --host localhost --port "$FRONTEND_PORT" --strictPort
' &
frontend_pid=$!

# Waits for $1 to answer while the process $2 that should be serving it is alive: if it died (e.g. it
# lost a race for the port), whatever answers is some other instance, which this one must not use.
wait_for_url() {
  local url="$1" pid="$2"
  for _ in {1..100}; do
    kill -0 "$pid" 2>/dev/null || { echo "The server for ${url} exited during startup" >&2; return 1; }
    if curl --silent --fail --output /dev/null "$url"; then return 0; fi
    sleep 0.2
  done
  echo "Timed out waiting for ${url}" >&2
  return 1
}

wait_for_url "${BACKEND_URL}/api/v1/health" "$backend_pid"
wait_for_url "${FRONTEND_URL}" "$frontend_pid"

echo "Launching Electron (API: ${BACKEND_URL})"
(
  cd frontend
  OPENBOT_API_URL="$BACKEND_URL" OPENBOT_URL="$FRONTEND_URL" pnpm electron
)
