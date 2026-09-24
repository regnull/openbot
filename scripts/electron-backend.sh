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
# `uv run --project` otherwise builds .venv inside PROJECT_ROOT, i.e. Contents/Resources of the
# app bundle itself. An installed, signed app's bundle is not reliably writable (and writing into
# it post-signing can break Gatekeeper verification), so keep the venv in the same always-writable
# per-user directory as the database, workspace, and logs.
export UV_PROJECT_ENVIRONMENT="${OPENBOT_USER_DATA}/venv"

# A GUI-launched app (double-clicked, not run from a terminal) gets a minimal launchd PATH that
# does not include a user-local install directory, so `command -v uv` alone misses the common
# install locations of uv's own installer and popular package managers. Check those explicitly
# before giving up.
find_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if ! UV="$(find_uv)"; then
  echo "OpenBot requires uv to run its bundled backend. Install uv from https://docs.astral.sh/uv/" >&2
  exit 127
fi
# No .venv ships in the bundle (see electron-builder.yml): a venv uv builds has an absolute
# shebang back to wherever it was built, so a pre-built one would work only on the machine that
# packaged the app. `uv run` here builds one rooted in this actual installed copy instead.
exec "$UV" run --project "$PROJECT_ROOT/backend" uvicorn openbot.main:app --host 127.0.0.1 --port "$PORT"
