"""Model Context Protocol servers as a tool source (docs/superpowers/specs/2026-09-17-mcp-design.md)."""
from __future__ import annotations

import logging
from pathlib import Path

from openbot.mcp.manager import McpManager
from openbot.mcp.oauth import DbTokenStorage
from openbot.mcp.store import McpServerStore, import_mcp_file
from openbot.runtime.secrets import resolve_secret_key

log = logging.getLogger(__name__)


async def build_mcp_manager(services) -> McpManager:
    """Servers come from the `mcp_servers` table. If `MCP_CONFIG` (mcp.json) exists, servers it names that
    were never imported are imported first; the file is otherwise ignored.

    The credential key is loaded lazily, the first time a secret has to be encrypted or decrypted, so an
    install with no MCP servers never needs (or writes) one. A key that cannot be used (bad
    MCP_TOKEN_KEY, unwritable key file) must not take the boot down: the manager comes up with no servers
    and the API reports the problem on every MCP call."""
    settings = services.settings

    def key() -> str:
        return resolve_secret_key(settings)

    store = McpServerStore(services.session_factory, key)
    try:
        await import_mcp_file(store, Path(settings.mcp_config))
        servers = await store.configs()
    except Exception as e:  # noqa: BLE001 - see docstring
        msg = f"MCP configuration unavailable (check MCP_TOKEN_KEY / MCP_TOKEN_KEY_FILE): {type(e).__name__}: {e}"
        log.error(msg)
        mgr = McpManager([], services.registry, settings, None, store=None)
        mgr.init_error = msg
        return mgr

    def storage(name: str, url: str | None = None) -> DbTokenStorage:
        return DbTokenStorage(services.session_factory, name, key(), url=url)

    return McpManager(servers, services.registry, settings, storage, store=store)


__all__ = ["McpManager", "McpServerStore", "build_mcp_manager"]
