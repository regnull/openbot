"""Model Context Protocol servers as a tool source (docs/superpowers/specs/2026-09-17-mcp-design.md)."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from openbot.db.models import McpServer
from openbot.mcp.config import McpConfigError, McpServerConfig, load_mcp_config
from openbot.mcp.manager import McpManager
from openbot.mcp.oauth import DbTokenStorage, load_or_create_key

log = logging.getLogger(__name__)


def server_from_row(row: McpServer) -> McpServerConfig:
    return McpServerConfig(name=row.name, transport="http", url=row.url, headers=dict(row.headers or {}),
                           enabled=row.enabled, source="db")


async def build_mcp_manager(services) -> McpManager:
    """Servers from `MCP_CONFIG` plus those added from the Settings UI (the `mcp_servers` table). A broken
    file is logged and yields no file servers; a database row colliding with a file name is skipped, the
    file wins. The credential key is created lazily, the first time an OAuth server needs it."""
    settings = services.settings
    try:
        servers = load_mcp_config(Path(settings.mcp_config))
    except McpConfigError as e:
        log.error("MCP config not loaded: %s", e)
        servers = []
    names = {s.name for s in servers}
    async with services.session_factory() as session:
        rows = (await session.execute(select(McpServer).order_by(McpServer.created_at))).scalars().all()
    for row in rows:
        if row.name in names:
            log.warning("MCP server %s is defined both in %s and in the database; using the file", row.name, settings.mcp_config)
            continue
        servers.append(server_from_row(row))
    key_holder: dict[str, str] = {}

    def storage(name: str, url: str | None = None) -> DbTokenStorage:
        if "key" not in key_holder:
            key_holder["key"] = load_or_create_key(settings.mcp_token_key, Path(settings.mcp_token_key_file))
        return DbTokenStorage(services.session_factory, name, key_holder["key"], url=url)

    return McpManager(servers, services.registry, settings, storage)


__all__ = ["McpManager", "build_mcp_manager", "server_from_row"]
