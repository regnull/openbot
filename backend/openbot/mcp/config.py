"""MCP server specs: Claude Code's `mcpServers` shape, with `${VAR}` expansion from the environment.

Specs are stored in the database (see `store.py`); `mcp.json` is only an import source. A spec is a
plain dict (`command`/`args`/`env`/`cwd` for stdio, `url`/`headers` for HTTP, `enabled`), and
`build_server` turns it into the `McpServerConfig` the manager connects. `${VAR}` is expanded at that
point, so a stored value such as `"Authorization": "Bearer ${LINEAR_KEY}"` keeps the secret in the
server environment. An unset variable marks that one server as errored instead of silently
expanding to an empty string.
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
SECRET_FIELDS = ("headers", "env")


class McpConfigError(ValueError):
    """The spec or file is unusable (bad JSON, bad shape). Per-server expansion problems go on the server."""


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
    source: str = "db"

    @property
    def oauth(self) -> bool:
        """A remote server with no static Authorization header authenticates with OAuth when it asks to."""
        return self.transport == "http" and not any(k.lower() == "authorization" for k in self.headers)


class _Unset(KeyError):
    pass


def check_url(value: str) -> str:
    """A remote server URL must be absolute and https, or http to localhost. Values still holding a
    `${VAR}` reference are accepted here and checked again after expansion, in `build_server`."""
    from urllib.parse import urlparse
    value = value.strip()
    if "${" in value:
        return value
    u = urlparse(value)
    if not u.netloc:
        raise ValueError("url must be absolute, for example https://mcp.example.com/mcp")
    local = u.hostname in ("localhost", "127.0.0.1", "::1")
    if u.scheme != "https" and not (u.scheme == "http" and local):
        raise ValueError("url must use https (http is allowed for localhost only)")
    return value


def _expand(value: str, env: Mapping[str, str]) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in env:
            raise _Unset(name)
        return env[name]
    return VAR_RE.sub(sub, value)


def _expand_map(values: Mapping[str, str], env: Mapping[str, str]) -> dict[str, str]:
    return {k: _expand(str(v), env) for k, v in values.items()}


def validate_spec(name: str, spec: dict, where: str = "spec") -> dict:
    """Check a server spec's shape and return it normalised (only known keys, proper types)."""
    if not NAME_RE.match(name or ""):
        raise McpConfigError(f"{where}: server name {name!r} may only contain letters, digits, _ and - (up to 40)")
    if not isinstance(spec, dict):
        raise McpConfigError(f"{where}: server {name!r} must be an object")
    has_cmd, has_url = bool(spec.get("command")), bool(spec.get("url"))
    if has_cmd == has_url:
        raise McpConfigError(f"{where}: server {name!r} needs exactly one of \"command\" (stdio) or \"url\" (http)")
    out: dict = {"enabled": bool(spec.get("enabled", True))}
    if has_cmd:
        out["command"] = str(spec["command"])
        args = spec.get("args") or []
        if not isinstance(args, list):
            raise McpConfigError(f"{where}: server {name!r}: args must be a list")
        out["args"] = [str(a) for a in args]
        out["env"] = _str_map(spec.get("env"), f"{where}: server {name!r}: env")
        out["cwd"] = str(spec["cwd"]) if spec.get("cwd") else None
    else:
        out["url"] = str(spec["url"]).strip()
        out["headers"] = _str_map(spec.get("headers"), f"{where}: server {name!r}: headers")
    return out


def _str_map(value, where: str) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise McpConfigError(f"{where} must be an object of strings")
    return {str(k): str(v) for k, v in value.items()}


def build_server(name: str, spec: dict, env: Mapping[str, str] | None = None, source: str = "db") -> McpServerConfig:
    """A connectable config from a (validated) spec, with `${VAR}` expanded from `env`."""
    env = os.environ if env is None else env
    server = McpServerConfig(name=name, transport="stdio" if spec.get("command") else "http",
                             enabled=bool(spec.get("enabled", True)), source=source)
    try:
        if server.transport == "stdio":
            server.command = _expand(str(spec["command"]), env)
            server.args = [_expand(str(a), env) for a in spec.get("args") or []]
            server.env = _expand_map(spec.get("env") or {}, env)
            server.cwd = _expand(str(spec["cwd"]), env) if spec.get("cwd") else None
        else:
            server.url = check_url(_expand(str(spec["url"]), env))
            server.headers = _expand_map(spec.get("headers") or {}, env)
    except _Unset as e:
        server.error = f"environment variable {e.args[0]} is not set"
    except ValueError as e:                  # the expanded URL failed the https-or-localhost rule
        server.error = str(e)
    if spec.get("secrets_unreadable"):
        server.error = "stored headers/env cannot be read with the current MCP_TOKEN_KEY; re-enter them or restore the key"
    return server


def parse_mcp_file(path: Path | str) -> dict[str, dict]:
    """Raw, validated specs from an `mcpServers` file; `{}` when the file does not exist."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise McpConfigError(f"{path}: {e}") from e
    servers_raw = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers_raw, dict):
        raise McpConfigError(f'{path}: expected an object with an "mcpServers" object')
    return {name: validate_spec(name, spec, str(path)) for name, spec in servers_raw.items()}


def load_mcp_config(path: Path | str, env: Mapping[str, str] | None = None) -> list[McpServerConfig]:
    """Parse and build every server in a file (used by the import and by tests)."""
    return [build_server(name, spec, env, source="file") for name, spec in parse_mcp_file(path).items()]
