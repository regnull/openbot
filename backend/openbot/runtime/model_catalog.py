"""Model catalog from models.dev, filtered to what the agent loop can use and cached in the database.

See docs/superpowers/specs/2026-09-27-model-catalog-design.md. The picker in the UI reads this through
GET /api/v1/models; the provider factory (providers.py) does not depend on it, so a model typed by hand
that the catalog has never heard of still works.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from openbot.db.models import ModelCatalogRow, utcnow

log = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
MIN_CONTEXT = 32_000
CATALOG_TTL = timedelta(hours=24)
FETCH_TIMEOUT = 20.0
# OpenBot provider id -> models.dev provider id. Ollama's entry is the set of models Ollama itself serves;
# their ids are library names (gpt-oss:20b), so they are also what `ollama pull` takes.
CATALOG_SOURCES: dict[str, str] = {"openai": "openai", "anthropic": "anthropic", "openrouter": "openrouter", "ollama": "ollama-cloud"}
CATALOG_PROVIDERS: tuple[str, ...] = tuple(CATALOG_SOURCES)


def _fit_for_agents(m: dict) -> bool:
    """Bots call tools on every run and need room for a system prompt, tool schemas and history, so
    anything without tool calling, without text in and out, deprecated, or under MIN_CONTEXT is noise."""
    mod = m.get("modalities") or {}
    context = (m.get("limit") or {}).get("context")
    return (bool(m.get("tool_call"))
            and "text" in (mod.get("input") or []) and "text" in (mod.get("output") or [])
            and m.get("status") != "deprecated"
            and context is not None and context >= MIN_CONTEXT)


def _effort_levels(m: dict) -> list[str]:
    for opt in m.get("reasoning_options") or []:
        if isinstance(opt, dict) and opt.get("type") == "effort":
            return [str(v) for v in opt.get("values") or []]
    return []


def normalize_model(key: str, m: dict) -> dict:
    mod = m.get("modalities") or {}
    limit = m.get("limit") or {}
    cost = m.get("cost") or {}
    return {
        "id": str(m.get("id") or key),
        "name": str(m.get("name") or key),
        "family": str(m.get("family") or ""),
        "description": str(m.get("description") or ""),
        "reasoning": bool(m.get("reasoning")),
        "effort_levels": _effort_levels(m),
        "image_input": "image" in (mod.get("input") or []),
        "context": int(limit["context"]),
        "output": int(limit["output"]) if limit.get("output") is not None else None,
        "cost_input": float(cost["input"]) if cost.get("input") is not None else None,
        "cost_output": float(cost["output"]) if cost.get("output") is not None else None,
        "release_date": str(m.get("release_date") or ""),
        "status": "beta" if m.get("status") == "beta" else None,
    }


def normalize_catalog(raw: Any) -> dict[str, list[dict]]:
    """models.dev document -> {openbot provider: [normalized model, ...]} for CATALOG_SOURCES only.

    Unfit models are dropped (see _fit_for_agents). A malformed entry is skipped with a warning and never
    drops its provider; a provider missing from the document yields an empty list."""
    if not isinstance(raw, dict):
        raise ValueError("models.dev document is not an object")  # noqa: TRY004
    out: dict[str, list[dict]] = {}
    for provider, source in CATALOG_SOURCES.items():
        block = raw.get(source)
        entries = block.get("models") if isinstance(block, dict) else None
        models: list[dict] = []
        for key, m in (entries if isinstance(entries, dict) else {}).items():
            if not isinstance(m, dict):
                log.warning("models.dev %s/%s: entry is not an object, skipped", source, key)
                continue
            try:
                if _fit_for_agents(m):
                    models.append(normalize_model(str(key), m))
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                # AttributeError: non-dict modalities/limit/cost block surfaces when .get() is called on it
                log.warning("models.dev %s/%s: malformed entry skipped: %s", source, key, e)
        models.sort(key=lambda x: x["release_date"], reverse=True)
        out[provider] = models
    return out


@dataclass(frozen=True)
class CatalogResult:
    provider: str
    models: list[dict]
    fetched_at: datetime
    stale: bool


class ModelCatalog:
    """Serves the cached catalog and refreshes it in the background once it is older than the TTL.

    `get` never waits for the network: a request that finds no row, or a stale one, gets what is there
    (or None) and kicks off one refresh, so the UI degrades to the builtin list rather than to an error.
    One refresh task at a time; concurrent misses share it."""

    def __init__(self, session_factory: async_sessionmaker, http_client: httpx.AsyncClient | None,
                 url: str = MODELS_DEV_URL, ttl: timedelta = CATALOG_TTL) -> None:
        self._sessions = session_factory
        self._http = http_client
        self._url = url
        self._ttl = ttl
        self._task: asyncio.Task | None = None

    async def get(self, provider: str) -> CatalogResult | None:
        if provider not in CATALOG_SOURCES:
            raise ValueError(f"no catalog for provider {provider}")
        async with self._sessions() as session:
            row = await session.get(ModelCatalogRow, provider)
        if row is None:
            self.schedule_refresh()
            return None
        stale = utcnow() - row.fetched_at > self._ttl
        if stale:
            self.schedule_refresh()
        return CatalogResult(provider, list(row.models), row.fetched_at, stale)

    def schedule_refresh(self) -> asyncio.Task | None:
        """Start one background refresh unless one is already running. Returns the task so callers
        (tests, shutdown) can await or cancel it; None when there is no HTTP client to fetch with."""
        if self._http is None:
            return None
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.refresh(), name="model-catalog-refresh")
        return self._task

    async def refresh(self) -> bool:
        """Fetch, normalize and store every provider. False (and a warning) on any failure; rows are untouched."""
        if self._http is None:
            return False
        try:
            r = await self._http.get(self._url, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
            catalog = normalize_catalog(r.json())
        except Exception as e:  # noqa: BLE001 - any failure must leave the cached rows in place
            log.warning("model catalog refresh from %s failed: %s", self._url, e)
            return False
        now = utcnow()
        async with self._sessions() as session:
            for provider, models in catalog.items():
                await session.merge(ModelCatalogRow(provider=provider, models=models, fetched_at=now))
            await session.commit()
        log.info("model catalog refreshed: %s", ", ".join(f"{p}={len(m)}" for p, m in catalog.items()))
        return True

    async def close(self) -> None:
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110 - shutdown must not raise
                pass
