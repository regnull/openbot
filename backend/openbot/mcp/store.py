"""MCP server specs in the database: the single source of truth for which servers exist.

Secrets (`headers`, `env`) are Fernet-encrypted at rest with the same key as OAuth credentials and
masked when read back for the UI. `${VAR}` references are stored as written and expanded only when
a connectable config is built, so a secret can still live in the server environment.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from openbot.db.models import McpServer, utcnow
from openbot.mcp.config import (
    SECRET_FIELDS,
    McpConfigError,
    McpServerConfig,
    build_server,
    parse_mcp_file,
    validate_spec,
)

log = logging.getLogger(__name__)

MASK = "••••••••"


class McpServerStore:
    def __init__(self, session_factory: async_sessionmaker, key: str) -> None:
        self._sf = session_factory
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    # --- (de)serialisation ------------------------------------------------------------------------------

    def _encrypt_secrets(self, spec: dict) -> str | None:
        secrets = {k: spec[k] for k in SECRET_FIELDS if spec.get(k)}
        return self._fernet.encrypt(json.dumps(secrets).encode()).decode() if secrets else None

    def _decrypt_secrets(self, blob: str | None, name: str) -> dict:
        if not blob:
            return {}
        try:
            return json.loads(self._fernet.decrypt(blob.encode()))
        except (InvalidToken, ValueError):
            log.warning("MCP server %s: stored headers/env cannot be read (key changed?); treating as empty", name)
            return {}

    def _spec(self, row: McpServer) -> dict:
        secrets = self._decrypt_secrets(row.secrets, row.name)
        spec: dict = {"enabled": row.enabled}
        if row.transport == "stdio":
            spec.update(command=row.command, args=list(row.args or []), env=dict(secrets.get("env") or {}), cwd=row.cwd)
        else:
            spec.update(url=row.url, headers=dict(secrets.get("headers") or {}))
        return spec

    @staticmethod
    def _apply(row: McpServer, spec: dict, secrets_blob: str | None) -> None:
        row.transport = "stdio" if spec.get("command") else "http"
        row.command, row.args, row.cwd = spec.get("command"), spec.get("args") or [], spec.get("cwd")
        row.url = spec.get("url")
        row.secrets = secrets_blob
        row.enabled = bool(spec.get("enabled", True))
        row.updated_at = utcnow()

    # --- queries ----------------------------------------------------------------------------------------

    async def names(self) -> list[str]:
        async with self._sf() as s:
            return list((await s.execute(select(McpServer.name).order_by(McpServer.created_at))).scalars().all())

    async def raw(self, name: str) -> dict | None:
        """The stored spec with real secret values (for building configs and applying updates)."""
        async with self._sf() as s:
            row = await s.get(McpServer, name)
        return None if row is None else self._spec(row)

    async def get(self, name: str) -> dict | None:
        """The stored spec with secrets masked (what the UI sees)."""
        spec = await self.raw(name)
        return None if spec is None else mask(spec)

    async def configs(self, env: Mapping[str, str] | None = None) -> list[McpServerConfig]:
        async with self._sf() as s:
            rows = (await s.execute(select(McpServer).order_by(McpServer.created_at))).scalars().all()
        return [build_server(row.name, self._spec(row), env) for row in rows]

    # --- writes -----------------------------------------------------------------------------------------

    async def upsert(self, spec: dict) -> dict:
        name = spec.get("name", "")
        clean = validate_spec(name, {k: v for k, v in spec.items() if k != "name"})
        async with self._sf() as s:
            row = await s.get(McpServer, name)
            if row is None:
                row = McpServer(name=name)
                s.add(row)
            self._apply(row, clean, self._encrypt_secrets(clean))
            await s.commit()
        return mask(clean)

    async def update(self, name: str, changes: dict) -> dict:
        """Partial update. For `headers`/`env`, the dict sent replaces the stored one, except that an
        empty value for a key that already exists keeps the stored (secret) value: the UI shows masks and
        sends them back blank."""
        current = await self.raw(name)
        if current is None:
            raise KeyError(name)
        merged = dict(current)
        for k, v in changes.items():
            if k in SECRET_FIELDS and isinstance(v, dict):
                existing = current.get(k) or {}
                merged[k] = {key: (existing.get(key, "") if val in ("", None) else val) for key, val in v.items()}
            elif k != "name":
                merged[k] = v
        clean = validate_spec(name, merged)
        async with self._sf() as s:
            row = await s.get(McpServer, name)
            self._apply(row, clean, self._encrypt_secrets(clean))
            await s.commit()
        return mask(clean)

    async def delete(self, name: str) -> bool:
        async with self._sf() as s:
            row = await s.get(McpServer, name)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
        return True


def mask(spec: dict) -> dict:
    out = dict(spec)
    for k in SECRET_FIELDS:
        if out.get(k):
            out[k] = dict.fromkeys(out[k], MASK)
    return out


IMPORTED_KEY = "mcp.imported_servers"   # AppSetting row remembering which file entries were imported


async def import_mcp_file(store: McpServerStore, path: Path | str) -> list[str]:
    """One-time import of an `mcpServers` file. Each entry is imported once, by name, with its spec as
    written (`${VAR}` unexpanded). Names already in the database or already imported before are left
    alone, so an operator's later edits or deletions win over the file on every subsequent start."""
    try:
        specs = parse_mcp_file(path)
    except McpConfigError as e:
        log.error("MCP config file not imported: %s", e)
        return []
    if not specs:
        return []
    from openbot.db.models import AppSetting
    async with store._sf() as s:
        marker = await s.get(AppSetting, IMPORTED_KEY)
        imported: list[str] = list(marker.value) if marker and isinstance(marker.value, list) else []
    have = set(await store.names()) | set(imported)
    added = []
    for name, spec in specs.items():
        if name in have:
            continue
        await store.upsert({"name": name, **spec})
        added.append(name)
    if added:
        async with store._sf() as s:
            marker = await s.get(AppSetting, IMPORTED_KEY)
            if marker is None:
                s.add(AppSetting(key=IMPORTED_KEY, value=[*imported, *added], updated_at=utcnow()))
            else:
                marker.value, marker.updated_at = [*imported, *added], utcnow()
            await s.commit()
        log.info("imported %d MCP server(s) from %s into the database: %s. The file is no longer read for "
                 "configuration; it can be deleted.", len(added), path, ", ".join(added))
    return added
