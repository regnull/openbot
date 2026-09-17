"""Model Context Protocol servers as a tool source (docs/superpowers/specs/2026-09-17-mcp-design.md)."""
from __future__ import annotations

import logging
from pathlib import Path

from openbot.mcp.manager import McpManager
from openbot.mcp.oauth import DbTokenStorage, load_or_create_key
from openbot.mcp.store import McpServerStore, import_mcp_file

log = logging.getLogger(__name__)


async def build_mcp_manager(services) -> McpManager:
    """Servers come from the `mcp_servers` table. If `MCP_CONFIG` (mcp.json) exists, servers it names that
    are not in the table yet are imported first, once; the file is otherwise ignored."""
    settings = services.settings
    key = load_or_create_key(settings.mcp_token_key, Path(settings.mcp_token_key_file))
    store = McpServerStore(services.session_factory, key)
    await import_mcp_file(store, Path(settings.mcp_config))
    servers = await store.configs()

    def storage(name: str, url: str | None = None) -> DbTokenStorage:
        return DbTokenStorage(services.session_factory, name, key, url=url)

    return McpManager(servers, services.registry, settings, storage, store=store)


__all__ = ["McpManager", "McpServerStore", "build_mcp_manager"]
