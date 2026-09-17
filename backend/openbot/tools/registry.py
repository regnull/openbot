from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import BaseTool

log = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    source: str
    tool: BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self.load_errors: list[dict] = []

    def register(self, tool: BaseTool, source: str = "builtin") -> None:
        if tool.name in self._tools:
            log.warning("tool %s from %s overrides %s", tool.name, source, self._tools[tool.name].source)
        self._tools[tool.name] = ToolSpec(tool.name, tool.description or "", source, tool)

    def unregister_source(self, source: str) -> list[str]:
        """Drop every tool registered from `source` (an MCP server disconnecting); returns their names."""
        names = [n for n, spec in self._tools.items() if spec.source == source]
        for n in names:
            del self._tools[n]
        return names

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> BaseTool:
        return self._tools[name].tool

    def resolve(self, names: list[str]) -> list[BaseTool]:
        """Return the named tools, dropping any the registry does not know.

        The registry is snapshotted at startup while bot tool lists live in the DB
        and can change underneath a running server, so an unknown name usually means
        the list was updated after this process started. Warn and drop instead of
        failing the whole run; unknown tools are still rejected by API validation
        when a profile is written.
        """
        missing = [n for n in names if n not in self._tools]
        if missing:
            log.warning("dropping unknown tools %s (tool list changed since server start? "
                        "restart to pick up new tools)", missing)
        return [self._tools[n].tool for n in names if n in self._tools]

    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def load_plugins(self, tools_dir: Path) -> None:
        if not tools_dir.is_dir():
            return
        for path in sorted(tools_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            mod_name = f"openbot_plugins.{path.stem}"
            try:
                spec = importlib.util.spec_from_file_location(mod_name, path)
                module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)  # type: ignore[union-attr]
            except Exception as e:
                log.exception("failed to load plugin %s", path)
                self.load_errors.append({"file": str(path), "error": f"{type(e).__name__}: {e}"})
                continue
            found = 0
            for obj in vars(module).values():
                if isinstance(obj, BaseTool):
                    self.register(obj, source=str(path))
                    found += 1
            log.info("loaded %d tools from %s", found, path)


def build_registry(settings) -> ToolRegistry:
    from openbot.tools.builtin import SELECTABLE_TOOLS

    reg = ToolRegistry()
    for t in SELECTABLE_TOOLS:
        reg.register(t)
    reg.load_plugins(Path(settings.tools_dir))
    return reg
