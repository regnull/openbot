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

ELECTRON_BACKEND_PORT="${ELECTRON_BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_URL="http://localhost:${ELECTRON_BACKEND_PORT}"
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"

backend_pid=""
frontend_pid=""
kill_process_group() {
  local pid="$1"
  [[ -z "$pid" ]] && return 0

  # uvicorn --reload and Vite each create children. Kill the process group so
  # those children do not outlive the launcher, then escalate if necessary.
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

# Use the same root-relative commands as the Makefile targets. OPENBOT_API_URL is passed to
# Electron/preload so packaged-style absolute API requests use this dedicated backend, and
# VITE_BACKEND_PORT points Vite's own dev proxy (relative /api/* fetches from the loaded page)
# at the same port, so both request paths reach the one backend actually running here.
echo "Starting Electron backend on ${BACKEND_URL}"
# --reload-dir scopes the file watcher to actual source: without it, uvicorn watches this whole
# repo root recursively -- .venv, node_modules, and every git worktree checked out under it -- which
# can exceed 100k files and has wedged the reload watcher outright during unrelated git activity
# elsewhere in the tree.
run_in_process_group uv run --project backend uvicorn openbot.main:app --reload --reload-dir backend/openbot --reload-dir tools --port "$ELECTRON_BACKEND_PORT" &
backend_pid=$!

echo "Starting Vite frontend on ${FRONTEND_URL}"
run_in_process_group env FRONTEND_PORT="$FRONTEND_PORT" VITE_BACKEND_PORT="$ELECTRON_BACKEND_PORT" bash -c '
  cd frontend
  pnpm dev --host localhost --port "$FRONTEND_PORT"
' &
frontend_pid=$!

wait_for_url() {
  local url="$1"
  for _ in {1..100}; do
    if curl --silent --fail --output /dev/null "$url"; then return 0; fi
    sleep 0.2
  done
  echo "Timed out waiting for ${url}" >&2
  return 1
}

wait_for_url "${BACKEND_URL}/api/v1/health"
wait_for_url "${FRONTEND_URL}"

echo "Launching Electron (API: ${BACKEND_URL})"
(
  cd frontend
  OPENBOT_API_URL="$BACKEND_URL" OPENBOT_URL="$FRONTEND_URL" pnpm electron
)
