"""Model Context Protocol servers as a tool source (docs/superpowers/specs/2026-09-17-mcp-design.md)."""
from __future__ import annotations

import logging
from pathlib import Path

from openbot.mcp.config import McpConfigError, load_mcp_config
from openbot.mcp.manager import McpManager
from openbot.mcp.oauth import DbTokenStorage, load_or_create_key

log = logging.getLogger(__name__)


def build_mcp_manager(services) -> McpManager:
    """Read `MCP_CONFIG` and build the manager. A broken file is logged and yields no servers; the
    credential key is created lazily, the first time an OAuth server needs it."""
    settings = services.settings
    try:
        servers = load_mcp_config(Path(settings.mcp_config))
    except McpConfigError as e:
        log.error("MCP config not loaded: %s", e)
        servers = []
    key_holder: dict[str, str] = {}

    def storage(name: str) -> DbTokenStorage:
        if "key" not in key_holder:
            key_holder["key"] = load_or_create_key(settings.mcp_token_key, Path(settings.mcp_token_key_file))
        return DbTokenStorage(services.session_factory, name, key_holder["key"])

    return McpManager(servers, services.registry, settings, storage)


__all__ = ["McpManager", "build_mcp_manager"]
