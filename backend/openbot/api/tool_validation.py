from __future__ import annotations

from openbot.services import Services
from openbot.skills import discover_skills


def known_tool(services: Services, name: str) -> bool:
    """Return whether a tool is registered or belongs to a configured MCP server."""
    if services.registry is not None and services.registry.has(name):
        return True
    if services.mcp is not None and "__" in name:
        return services.mcp.has(name.split("__", 1)[0])
    return False


def known_skill_names(services: Services) -> set[str]:
    """Skill ids and names discoverable right now (workspace + state dir), case-folded.

    Tolerates a None settings registry the same way known_tool does, so tests and early
    boot can call it.
    """
    settings = getattr(services, "settings", None)
    if settings is None:
        return set()
    roots = [settings.workspace_root]
    state_dir = getattr(settings, "state_dir", None)
    if state_dir is not None:
        roots.append(state_dir)
    skills = discover_skills(*[root for root in roots if root is not None])
    folded = {s.id.lower() for s in skills}
    folded.update(s.name.lower() for s in skills)
    return folded
