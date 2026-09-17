"""mcp.json: Claude Code's `mcpServers` shape, with `${VAR}` expansion from the server environment.

Secrets never sit in the file: a value such as `"Authorization": "Bearer ${LINEAR_KEY}"` is filled from
the environment (`.env` is loaded there). An unset variable marks that one server as errored instead
of silently expanding to an empty string, and does not stop the others from loading.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")
VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class McpConfigError(ValueError):
    """The config file itself is unusable (bad JSON, bad shape). Per-server problems go on the server."""


@dataclass
class McpServerConfig:
    name: str
    transport: str                        # "stdio" | "http"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    error: str | None = None              # set when expansion failed; the server is listed but not started
    source: str = "file"                  # "file" (mcp.json, read-only in the UI) | "db" (added from Settings)

    @property
    def oauth(self) -> bool:
        """A remote server with no static Authorization header authenticates with OAuth when it asks to."""
        return self.transport == "http" and not any(k.lower() == "authorization" for k in self.headers)


class _Unset(KeyError):
    pass


def _expand(value: str, env: Mapping[str, str]) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in env:
            raise _Unset(name)
        return env[name]
    return VAR_RE.sub(sub, value)


def _expand_map(values: Mapping[str, str], env: Mapping[str, str]) -> dict[str, str]:
    return {k: _expand(str(v), env) for k, v in values.items()}


def load_mcp_config(path: Path | str, env: Mapping[str, str] | None = None) -> list[McpServerConfig]:
    path = Path(path)
    if not path.is_file():
        return []
    env = os.environ if env is None else env
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise McpConfigError(f"{path}: {e}") from e
    servers_raw = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers_raw, dict):
        raise McpConfigError(f'{path}: expected an object with an "mcpServers" object')
    out: list[McpServerConfig] = []
    for name, spec in servers_raw.items():
        if not NAME_RE.match(name):
            raise McpConfigError(f"{path}: server name {name!r} may only contain letters, digits, _ and -")
        if not isinstance(spec, dict):
            raise McpConfigError(f"{path}: server {name!r} must be an object")
        has_cmd, has_url = bool(spec.get("command")), bool(spec.get("url"))
        if has_cmd == has_url:
            raise McpConfigError(f"{path}: server {name!r} needs exactly one of \"command\" (stdio) or \"url\" (http)")
        server = McpServerConfig(name=name, transport="stdio" if has_cmd else "http", enabled=bool(spec.get("enabled", True)))
        try:
            if has_cmd:
                server.command = _expand(str(spec["command"]), env)
                server.args = [_expand(str(a), env) for a in spec.get("args", [])]
                server.env = _expand_map(spec.get("env", {}), env)
                server.cwd = _expand(str(spec["cwd"]), env) if spec.get("cwd") else None
            else:
                server.url = _expand(str(spec["url"]), env)
                server.headers = _expand_map(spec.get("headers", {}), env)
        except _Unset as e:
            server.error = f"environment variable {e.args[0]} is not set"
        out.append(server)
    return out
