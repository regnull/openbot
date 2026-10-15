from __future__ import annotations

from openbot.services import Services


def known_tool(services: Services, name: str) -> bool:
    """Return whether a tool is registered or belongs to a configured MCP server."""
    if services.registry is not None and services.registry.has(name):
        return True
    if services.mcp is not None and "__" in name:
        return services.mcp.has(name.split("__", 1)[0])
    return False
