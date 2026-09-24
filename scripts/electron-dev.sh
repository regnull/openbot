#!/usr/bin/env bash
# Launch the Electron development app with its own backend and Vite server.
set -Eeuo pipefail

ELECTRON_BACKEND_PORT="${ELECTRON_BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_URL="http://127.0.0.1:${ELECTRON_BACKEND_PORT}"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"

backend_pid=""
frontend_pid=""
cleanup() {
  trap - EXIT INT TERM
  [[ -n "$frontend_pid" ]] && kill "$frontend_pid" 2>/dev/null || true
  [[ -n "$backend_pid" ]] && kill "$backend_pid" 2>/dev/null || true
  wait "$frontend_pid" "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Use the same root-relative commands as the Makefile targets. OPENBOT_API_URL is
# passed to Electron/preload so packaged-style absolute API requests use 8001,
# while the browser/Vite proxy remains pointed at make run's port 8000.
echo "Starting Electron backend on ${BACKEND_URL}"
uv run --project backend uvicorn openbot.main:app --reload --port "$ELECTRON_BACKEND_PORT" &
backend_pid=$!

echo "Starting Vite frontend on ${FRONTEND_URL}"
(
  cd frontend
  pnpm dev --host 127.0.0.1 --port "$FRONTEND_PORT"
) &
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

wait_for_url "${BACKEND_URL}/health"
wait_for_url "${FRONTEND_URL}"

echo "Launching Electron (API: ${BACKEND_URL})"
(
  cd frontend
  OPENBOT_API_URL="$BACKEND_URL" OPENBOT_URL="$FRONTEND_URL" pnpm electron
)
