# The backend in a container, the UI on the host. Usage is in compose.yaml. The backend stays
# root in here so it can start run_shell commands as the shell user below.
FROM python:3.13-bookworm

# tini as PID 1 reaps what killed commands leave behind. Without it every timed-out or cancelled
# run_shell that had a background process leaves a zombie, because the backend never waits on
# children that aren't its own.
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy

# run_shell commands run as this user (SHELL_USER), not as root. The workspace group lets it and
# the backend edit each other's files.
RUN groupadd --gid 1001 workspace \
    && useradd --uid 1001 --gid workspace --create-home --shell /bin/bash shell

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version backend/
RUN cd backend && uv sync --frozen --no-dev --no-install-project
COPY backend/ backend/
COPY tools/ tools/
RUN cd backend && uv sync --frozen --no-dev

# State lives in /data (root only), bots work in /workspace.
ENV DATABASE_URL=sqlite+aiosqlite:////data/openbot.db \
    SECRET_KEY_FILE=/data/secret.key \
    MCP_TOKEN_KEY_FILE=/data/mcp_token.key \
    MCP_CONFIG=/data/mcp.json \
    LOG_FILE=/data/logs/openbot.log \
    WORKSPACE_ROOT=/workspace \
    TOOLS_DIR=/app/tools

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--", "docker-entrypoint.sh"]
