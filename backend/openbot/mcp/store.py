"""MCP server specs in the database: the single source of truth for which servers exist.

Secrets (`headers`, `env`) are Fernet-encrypted at rest with the same key as OAuth credentials and
masked when read back for the UI. `${VAR}` references are stored as written and expanded only when
a connectable config is built, so a secret can still live in the server environment.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from openbot.db.models import AppSetting, McpServer, utcnow
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
UNREADABLE = object()       # what _decrypt_secrets returns when the stored blob cannot be read with this key


class McpKeyError(RuntimeError):
    """The credential key cannot be loaded or is not a valid Fernet key. Operator configuration, not data."""


class McpServerStore:
    def __init__(self, session_factory: async_sessionmaker, key: str | Callable[[], str]) -> None:
        self._sf = session_factory
        self._key = key
        self._fernet: Fernet | None = None

    @property
    def fernet(self) -> Fernet:
        """Built on first use, so an install with no secrets never needs (or creates) a key."""
        if self._fernet is None:
            try:
                key = self._key() if callable(self._key) else self._key
                self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
            except Exception as e:
                raise McpKeyError(f"MCP_TOKEN_KEY is not a valid Fernet key, or MCP_TOKEN_KEY_FILE cannot be used: "
                                  f"{type(e).__name__}: {e}") from e
        return self._fernet

    # --- (de)serialisation ------------------------------------------------------------------------------

    def _encrypt_secrets(self, spec: dict) -> str | None:
        secrets = {k: spec[k] for k in SECRET_FIELDS if spec.get(k)}
        return self.fernet.encrypt(json.dumps(secrets).encode()).decode() if secrets else None

    def _decrypt_secrets(self, blob: str | None, name: str):
        if not blob:
            return {}
        fernet = self.fernet                      # a bad key raises McpKeyError here, deliberately outside the try
        try:
            return json.loads(fernet.decrypt(blob.encode()))
        except (InvalidToken, ValueError):
            log.warning("MCP server %s: stored headers/env cannot be read with the current key", name)
            return UNREADABLE

    def _spec(self, row: McpServer) -> dict:
        secrets = self._decrypt_secrets(row.secrets, row.name)
        unreadable = secrets is UNREADABLE
        secrets = {} if unreadable else secrets
        spec: dict = {"enabled": row.enabled}
        if row.transport == "stdio":
            spec.update(command=row.command, args=list(row.args or []), env=dict(secrets.get("env") or {}), cwd=row.cwd)
        else:
            spec.update(url=row.url, headers=dict(secrets.get("headers") or {}))
        if unreadable:
            spec["secrets_unreadable"] = True
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

    async def all_masked(self) -> dict[str, dict]:
        """Every stored spec, masked, in one query (the Settings page polls the listing)."""
        async with self._sf() as s:
            rows = (await s.execute(select(McpServer).order_by(McpServer.created_at))).scalars().all()
        return {row.name: mask(self._spec(row)) for row in rows}

    async def configs(self, env: Mapping[str, str] | None = None) -> list[McpServerConfig]:
        async with self._sf() as s:
            rows = (await s.execute(select(McpServer).order_by(McpServer.created_at))).scalars().all()
        return [build_server(row.name, self._spec(row), env) for row in rows]

    async def config(self, name: str, env: Mapping[str, str] | None = None) -> McpServerConfig | None:
        spec = await self.raw(name)
        return None if spec is None else build_server(name, spec, env)

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
        """Partial update. For `headers`/`env` the dict sent replaces the stored one, except that a blank
        or masked value for a key that already exists keeps the stored secret (the UI shows masks and
        sends them back). If the stored secrets cannot be read with the current key, they are carried
        over untouched unless this update replaces them with real values, so a key rotation followed by
        an unrelated edit never destroys the old ciphertext."""
        current = await self.raw(name)
        if current is None:
            raise KeyError(name)
        unreadable = bool(current.get("secrets_unreadable"))
        merged = {k: v for k, v in current.items() if k != "secrets_unreadable"}
        replaces_secrets = False
        for k, v in changes.items():
            if k in SECRET_FIELDS and isinstance(v, dict):
                existing = current.get(k) or {}
                merged[k] = {key: (existing.get(key, "") if val in ("", None, MASK) else val) for key, val in v.items()}
                replaces_secrets = replaces_secrets or any(val not in ("", None, MASK) for val in v.values())
            elif k != "name":
                merged[k] = v
        clean = validate_spec(name, merged)
        async with self._sf() as s:
            row = await s.get(McpServer, name)
            blob = row.secrets if (unreadable and not replaces_secrets) else self._encrypt_secrets(clean)
            self._apply(row, clean, blob)
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
    out = {k: v for k, v in spec.items() if k != "secrets_unreadable"}
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
