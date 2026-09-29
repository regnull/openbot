#!/bin/sh
# Prepares /data and /workspace, then execs the backend. tini (PID 1) passes on the stop signal.
set -e

# Files the backend writes stay editable by the shell user (same group).
umask 002

mkdir -p /data/logs
chmod 700 /data

# /workspace is usually a bind mount, so on Linux this changes the host folder. Only touch it when
# it isn't set up already, and don't fail if the file system won't allow it.
mkdir -p /workspace
if [ "$(stat -c %G:%a /workspace)" != "workspace:2775" ]; then
    chgrp workspace /workspace && chmod 2775 /workspace \
        || echo "warning: could not make /workspace group-writable for the shell user" >&2
fi

exec /app/backend/.venv/bin/python -m openbot.cli --host 0.0.0.0 --port 8000 "$@"
