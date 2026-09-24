#!/usr/bin/env bash
# Backend entry point used by the packaged OpenBot macOS app.
set -Eeuo pipefail
PROJECT_ROOT="${OPENBOT_RESOURCES:?OPENBOT_RESOURCES is required}"
PORT="${OPENBOT_BACKEND_PORT:-8000}"
cd "$PROJECT_ROOT"
mkdir -p "${OPENBOT_USER_DATA:?OPENBOT_USER_DATA is required}/workspace" "${OPENBOT_USER_DATA}/logs"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///${OPENBOT_USER_DATA}/openbot.db}"
export WORKSPACE_ROOT="${WORKSPACE_ROOT:-${OPENBOT_USER_DATA}/workspace}"
export TOOLS_DIR="${TOOLS_DIR:-$PROJECT_ROOT/tools}"
export LOG_FILE="${LOG_FILE:-${OPENBOT_USER_DATA}/logs/openbot.log}"

if ! command -v uv >/dev/null 2>&1; then
  echo "OpenBot requires uv to run its bundled backend. Install uv from https://docs.astral.sh/uv/" >&2
  exit 127
fi
exec uv run --project "$PROJECT_ROOT/backend" uvicorn openbot.main:app --host 127.0.0.1 --port "$PORT"
