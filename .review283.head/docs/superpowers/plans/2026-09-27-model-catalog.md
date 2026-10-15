# Model Catalog, Model Picker and Effort Levels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve an agent-fit model catalog fetched from models.dev (cached in the database, refreshed in the background) and replace the free-text model inputs with a filtering picker that also exposes per-model reasoning effort levels.

**Architecture:** The backend fetches models.dev, keeps only tool-capable text models of OpenAI, Anthropic, OpenRouter and Ollama, stores one JSON row per provider in a new `model_catalog` table, and serves it at `GET /api/v1/models?provider=…` with stale-while-revalidate refresh after 24 hours and a builtin fallback before the first fetch. The frontend gets a `ModelPicker` combobox (grouped by family, filter chips, cost on every row, free text always accepted) used in the bot editor and for the Settings "Default bot model" tunable, plus an Effort select in the bot editor that only appears for models declaring effort levels. Anthropic receives `reasoning_effort` at runtime like the OpenAI-compatible providers already do.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async + Alembic, httpx (with `MockTransport` in tests), pytest (`asyncio_mode=auto`); React 19, TanStack Query v5, Tailwind v4, vitest 5 with jsdom (no testing-library: `createRoot` + `act`).

**Spec:** `docs/superpowers/specs/2026-09-27-model-catalog-design.md`

## Global Constraints

- Work in the worktree `/Users/regnull/work/openbot/.claude/worktrees/model-catalog` on branch `worktree-model-catalog`. Run every command from that directory (or its `backend/` and `frontend/` subdirectories). Never `cd` into the original checkout.
- Backend tests: `cd backend && uv run pytest -q <path>`; whole suite `uv run pytest -q`. Frontend: `cd frontend && pnpm exec vitest run <path>`, then `pnpm typecheck` and `pnpm lint`. Full check before finishing: `make test && make lint` from the worktree root.
- The frontend must not call external services or use `fetch` outside `src/api/client.ts` (`scripts/check-client-boundaries.py`, run by `make lint`).
- Catalog providers are exactly `openai`, `anthropic`, `openrouter`, `ollama`; the models.dev source for `ollama` is `ollama-cloud`. `xai` keeps its builtin list and is rejected by the models endpoint with 422.
- Agent-fitness filter, applied at ingest: `tool_call` true; `"text"` in both `modalities.input` and `modalities.output`; `status != "deprecated"`; `limit.context >= 32000`.
- Normalized record fields, exactly: `id, name, family, description, reasoning, effort_levels, image_input, context, output, cost_input, cost_output, release_date, status` (`status` is `null` or `"beta"`).
- `CATALOG_TTL` is 24 hours; fetch timeout 20 s; `GET /models` never awaits the network and never returns an error because the fetch failed.
- Cost text format: `$<in> / $<out> per M tokens`, `free` when both are 0, empty when both unknown; Ollama rows append ` on Ollama Cloud`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Existing style: docstrings and comments explain *why*; ruff line-length 100 is configured but E501 is not enforced, so match neighbouring code (~120 columns is common).

## Review Focus

1. **A typed model id in mixed case (`Claude-Opus-5-5`)**: the list must still filter to matching rows, and the value must be sent exactly as typed. Pinned in Task 6 (`filterModels` uppercase test) and Task 7 (free-text passthrough test).
2. **A provider row that exists but holds zero models** (every model filtered out): the endpoint returns `source: "catalog"` with an empty list and the picker shows "No matching models", never the builtin list and never a crash. Pinned in Task 4 (empty-row API test) and Task 7 (empty list test).
3. **A saved effort level the model no longer declares** (models.dev changed its values, or the operator switched models): the Effort select shows Default and the next save drops the key. Pinned in Task 8 (`reconcileEffort` on save test).
4. **An installed Ollama model the catalog does not know** (`qwen3:8b`, a custom tag): it must appear in the Installed group with a bare name, not be marked "not installed", and remain selectable. Pinned in Task 6 (`withSuggested`/`groupModels` test) and Task 7 (installed placeholder test).
5. **A models.dev document where a provider's `models` is missing or not an object**: that provider yields an empty list and the others are unaffected. Pinned in Task 2 (missing provider test).

---

### Task 1: `model_catalog` table and migration

**Files:**
- Modify: `backend/openbot/db/models.py` (append after `AppSetting`, ~line 275)
- Create: `backend/openbot/db/migrations/versions/0016_model_catalog.py`
- Test: `backend/tests/test_models.py` (append)

**Interfaces:**
- Consumes: `Base`, `UTCDateTime`, `utcnow` from `openbot.db.models`.
- Produces: `ModelCatalogRow(provider: str, models: list, fetched_at: datetime)` mapped to table `model_catalog`.

- [ ] **Step 1: Write the failing migration test**

Append to `backend/tests/test_models.py`:

```python
async def test_migration_creates_model_catalog_table(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("model_catalog")})
    await engine.dispose()
    assert cols == {"provider", "models", "fetched_at"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest -q tests/test_models.py::test_migration_creates_model_catalog_table`
Expected: FAIL (`NoSuchTableError` or empty column set).

- [ ] **Step 3: Add the ORM model**

Append to `backend/openbot/db/models.py`:

```python
class ModelCatalogRow(Base):
    """One provider's slice of the models.dev catalog, already filtered and normalized (see runtime/model_catalog.py)."""
    __tablename__ = "model_catalog"
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    models: Mapped[list] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
```

- [ ] **Step 4: Add the migration**

Create `backend/openbot/db/migrations/versions/0016_model_catalog.py`:

```python
"""model catalog cache

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "model_catalog",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("model_catalog")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && uv run pytest -q tests/test_models.py`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/openbot/db/models.py backend/openbot/db/migrations/versions/0016_model_catalog.py backend/tests/test_models.py
git commit -m "feat(db): add model_catalog table for the models.dev cache

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: models.dev normalizer and agent-fitness filter

**Files:**
- Create: `backend/openbot/runtime/model_catalog.py`
- Create: `backend/tests/fixtures/models_dev_sample.json`
- Create: `backend/tests/test_model_catalog.py`

**Interfaces:**
- Produces: `CATALOG_SOURCES: dict[str, str]`, `CATALOG_PROVIDERS: tuple[str, ...]`, `MIN_CONTEXT = 32_000`, `normalize_model(key: str, m: dict) -> dict`, `normalize_catalog(raw: Any) -> dict[str, list[dict]]` (raises `ValueError` when `raw` is not a dict; a missing provider yields `[]`; models sorted newest `release_date` first).

- [ ] **Step 1: Create the fixture**

Create `backend/tests/fixtures/models_dev_sample.json` (a hand-trimmed slice of the real document; every branch of the filter has a case):

```json
{
  "openai": {"id": "openai", "name": "OpenAI", "models": {
    "gpt-5.5": {"id": "gpt-5.5", "name": "GPT-5.5", "family": "gpt", "description": "Flagship", "reasoning": true,
      "reasoning_options": [{"type": "effort", "values": ["none", "low", "medium", "high", "xhigh"]}],
      "tool_call": true, "modalities": {"input": ["text", "image"], "output": ["text"]},
      "limit": {"context": 400000, "output": 128000}, "cost": {"input": 1.25, "output": 10}, "release_date": "2026-05-01"},
    "gpt-3.5-turbo": {"id": "gpt-3.5-turbo", "name": "GPT-3.5-turbo", "family": "gpt", "reasoning": false, "tool_call": true,
      "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 16385, "output": 4096},
      "cost": {"input": 0.5, "output": 1.5}, "release_date": "2023-03-01", "status": "deprecated"},
    "text-embedding-3-small": {"id": "text-embedding-3-small", "name": "text-embedding-3-small", "reasoning": false, "tool_call": false,
      "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 8191, "output": 0}, "release_date": "2024-01-25"},
    "gpt-image-2": {"id": "gpt-image-2", "name": "GPT Image 2", "reasoning": false, "tool_call": true,
      "modalities": {"input": ["text", "image"], "output": ["image"]}, "limit": {"context": 128000, "output": 0}, "release_date": "2026-02-01"},
    "gpt-nolimit": {"id": "gpt-nolimit", "name": "no limit block", "reasoning": false, "tool_call": true,
      "modalities": {"input": ["text"], "output": ["text"]}, "release_date": "2026-01-01"},
    "gpt-weird": {"id": "gpt-weird", "name": "context is a string", "reasoning": false, "tool_call": true,
      "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": "lots"}, "release_date": "2026-01-01"},
    "broken": "not-an-object"
  }},
  "anthropic": {"id": "anthropic", "name": "Anthropic", "models": {
    "claude-opus-5-5": {"id": "claude-opus-5-5", "name": "Claude Opus 5.5", "family": "claude-opus", "description": "Most capable Claude",
      "reasoning": true, "reasoning_options": [{"type": "effort", "values": ["low", "medium", "high", "xhigh", "max"]}],
      "tool_call": true, "modalities": {"input": ["text", "image", "pdf"], "output": ["text"]},
      "limit": {"context": 200000, "output": 64000}, "cost": {"input": 5, "output": 25, "cache_read": 0.5}, "release_date": "2026-03-01"},
    "claude-sonnet-4-5": {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5", "family": "claude-sonnet", "reasoning": true,
      "reasoning_options": [{"type": "budget_tokens", "min": 1024}], "tool_call": true,
      "modalities": {"input": ["text", "image"], "output": ["text"]}, "limit": {"context": 200000, "output": 64000},
      "cost": {"input": 3, "output": 15}, "release_date": "2025-09-29"},
    "claude-haiku-4-5": {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5", "family": "claude-haiku", "reasoning": true,
      "reasoning_options": [{"type": "toggle"}], "tool_call": true,
      "modalities": {"input": ["text", "image"], "output": ["text"]}, "limit": {"context": 200000, "output": 64000},
      "cost": {"input": 1, "output": 5}, "release_date": "2025-10-15"}
  }},
  "openrouter": {"id": "openrouter", "name": "OpenRouter", "models": {
    "z-ai/glm-5.3-flash": {"id": "z-ai/glm-5.3-flash", "name": "GLM 5.3 Flash", "family": "glm-flash", "reasoning": true,
      "reasoning_options": [{"type": "effort", "values": ["low", "medium", "high"]}], "tool_call": true,
      "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 200000, "output": 131072},
      "cost": {"input": 0.1, "output": 0.3}, "release_date": "2026-04-01"},
    "stealth/new-thing": {"id": "stealth/new-thing", "name": "New Thing", "family": "", "reasoning": false, "tool_call": true,
      "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 131072}, "release_date": "2026-01-01", "status": "beta"},
    "rekaai/reka-edge": {"id": "rekaai/reka-edge", "name": "Reka Edge", "reasoning": false, "tool_call": true,
      "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 8192, "output": 4096}, "release_date": "2024-03-01"},
    "meta-llama/llama-guard-4-12b": {"id": "meta-llama/llama-guard-4-12b", "name": "Llama Guard 4", "family": "llama", "reasoning": false,
      "tool_call": false, "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 163840}, "release_date": "2025-04-29"}
  }},
  "ollama-cloud": {"id": "ollama-cloud", "name": "Ollama Cloud", "models": {
    "gpt-oss:20b": {"id": "gpt-oss:20b", "name": "gpt-oss:20b", "family": "gpt-oss", "reasoning": true,
      "reasoning_options": [{"type": "effort", "values": ["low", "medium", "high"]}], "tool_call": true,
      "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 131072, "output": 32768},
      "cost": {"input": 0.07, "output": 0.3}, "release_date": "2025-08-05"},
    "kimi-k3": {"id": "kimi-k3", "name": "kimi-k3", "family": "kimi-k3", "reasoning": true, "reasoning_options": [{"type": "toggle"}],
      "tool_call": true, "modalities": {"input": ["text", "image"], "output": ["text"]}, "limit": {"context": 1048576, "output": 65536},
      "cost": {"input": 3, "output": 15}, "release_date": "2026-07-27"}
  }},
  "xai": {"id": "xai", "name": "xAI", "models": {
    "grok-4.6": {"id": "grok-4.6", "name": "Grok 4.6", "reasoning": true, "tool_call": true,
      "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 256000}, "release_date": "2026-02-01"}
  }}
}
```

- [ ] **Step 2: Write the failing normalizer tests**

Create `backend/tests/test_model_catalog.py`:

```python
import json
from pathlib import Path

import pytest

from openbot.runtime.model_catalog import CATALOG_PROVIDERS, normalize_catalog

SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "models_dev_sample.json").read_text())


def test_normalize_keeps_only_agent_capable_models_of_supported_providers():
    cat = normalize_catalog(SAMPLE)
    assert set(cat) == set(CATALOG_PROVIDERS) == {"openai", "anthropic", "openrouter", "ollama"}
    # deprecated, no tool calling, image output, no/invalid context and the malformed entry are all gone
    assert [m["id"] for m in cat["openai"]] == ["gpt-5.5"]
    # newest first; beta kept; tiny context and no-tools dropped
    assert [m["id"] for m in cat["openrouter"]] == ["z-ai/glm-5.3-flash", "stealth/new-thing"]
    assert [m["id"] for m in cat["ollama"]] == ["kimi-k3", "gpt-oss:20b"]
    assert "xai" not in cat


def test_normalized_record_shape():
    m = next(x for x in normalize_catalog(SAMPLE)["anthropic"] if x["id"] == "claude-opus-5-5")
    assert m == {
        "id": "claude-opus-5-5", "name": "Claude Opus 5.5", "family": "claude-opus", "description": "Most capable Claude",
        "reasoning": True, "effort_levels": ["low", "medium", "high", "xhigh", "max"], "image_input": True,
        "context": 200000, "output": 64000, "cost_input": 5.0, "cost_output": 25.0, "release_date": "2026-03-01", "status": None,
    }


def test_effort_levels_come_only_from_the_effort_option():
    by_id = {m["id"]: m for m in normalize_catalog(SAMPLE)["anthropic"]}
    assert by_id["claude-sonnet-4-5"]["effort_levels"] == []   # budget_tokens only
    assert by_id["claude-haiku-4-5"]["effort_levels"] == []    # toggle only
    assert by_id["claude-opus-5-5"]["reasoning"] is True


def test_beta_is_flagged_and_unknown_cost_and_output_are_null():
    m = next(x for x in normalize_catalog(SAMPLE)["openrouter"] if x["id"] == "stealth/new-thing")
    assert m["status"] == "beta" and m["family"] == "" and m["description"] == ""
    assert m["cost_input"] is None and m["cost_output"] is None and m["output"] is None


def test_missing_provider_or_models_block_yields_empty_list_without_touching_others():
    cat = normalize_catalog({"openai": {"models": SAMPLE["openai"]["models"]}, "anthropic": {"id": "anthropic"}, "openrouter": "garbage"})
    assert [m["id"] for m in cat["openai"]] == ["gpt-5.5"]
    assert cat["anthropic"] == [] and cat["openrouter"] == [] and cat["ollama"] == []


def test_document_must_be_an_object():
    with pytest.raises(ValueError):
        normalize_catalog([])
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd backend && uv run pytest -q tests/test_model_catalog.py`
Expected: FAIL with `ModuleNotFoundError: openbot.runtime.model_catalog`.

- [ ] **Step 4: Write the normalizer**

Create `backend/openbot/runtime/model_catalog.py` (the `ModelCatalog` class is added in Task 3):

```python
"""Model catalog from models.dev, filtered to what the agent loop can use and cached in the database.

See docs/superpowers/specs/2026-09-27-model-catalog-design.md. The picker in the UI reads this through
GET /api/v1/models; the provider factory (providers.py) does not depend on it, so a model typed by hand
that the catalog has never heard of still works.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
MIN_CONTEXT = 32_000
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
        raise ValueError("models.dev document is not an object")
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
            except (TypeError, ValueError, KeyError) as e:
                log.warning("models.dev %s/%s: malformed entry skipped: %s", source, key, e)
        models.sort(key=lambda x: x["release_date"], reverse=True)
        out[provider] = models
    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest -q tests/test_model_catalog.py`
Expected: 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/openbot/runtime/model_catalog.py backend/tests/fixtures/models_dev_sample.json backend/tests/test_model_catalog.py
git commit -m "feat(catalog): normalize models.dev into an agent-fit per-provider catalog

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `ModelCatalog` service with stale-while-revalidate refresh

**Files:**
- Modify: `backend/openbot/runtime/model_catalog.py` (append)
- Test: `backend/tests/test_model_catalog.py` (append)

**Interfaces:**
- Consumes: `ModelCatalogRow`, `utcnow` (Task 1); `normalize_catalog` (Task 2); the `services` pytest fixture (`services.session_factory`).
- Produces:
  - `CATALOG_TTL = timedelta(hours=24)`, `FETCH_TIMEOUT = 20.0`
  - `@dataclass(frozen=True) CatalogResult(provider: str, models: list[dict], fetched_at: datetime, stale: bool)`
  - `class ModelCatalog(session_factory, http_client: httpx.AsyncClient | None, url=MODELS_DEV_URL, ttl=CATALOG_TTL)` with `async get(provider) -> CatalogResult | None` (raises `ValueError` for a provider outside `CATALOG_SOURCES`), `schedule_refresh() -> asyncio.Task | None`, `async refresh() -> bool`, `async close() -> None`.

- [ ] **Step 1: Write the failing service tests**

Append to `backend/tests/test_model_catalog.py`:

```python
from datetime import timedelta

import httpx
from sqlalchemy import select

from openbot.db.models import ModelCatalogRow, utcnow
from openbot.runtime.model_catalog import MODELS_DEV_URL, ModelCatalog


def _catalog(services, handler) -> tuple[ModelCatalog, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ModelCatalog(services.session_factory, client), client


def _ok(request: httpx.Request) -> httpx.Response:
    assert str(request.url) == MODELS_DEV_URL
    return httpx.Response(200, json=SAMPLE)


async def _rows(services) -> dict[str, ModelCatalogRow]:
    async with services.session_factory() as s:
        return {r.provider: r for r in (await s.execute(select(ModelCatalogRow))).scalars()}


async def _seed(services, provider: str, models: list[dict], age: timedelta) -> None:
    async with services.session_factory() as s:
        s.add(ModelCatalogRow(provider=provider, models=models, fetched_at=utcnow() - age))
        await s.commit()


async def test_refresh_writes_one_row_per_provider(services):
    cat, client = _catalog(services, _ok)
    async with client:
        assert await cat.refresh() is True
    rows = await _rows(services)
    assert set(rows) == {"openai", "anthropic", "openrouter", "ollama"}
    assert [m["id"] for m in rows["ollama"].models] == ["kimi-k3", "gpt-oss:20b"]
    assert rows["openai"].fetched_at.tzinfo is not None


async def test_get_on_empty_db_returns_none_and_schedules_one_refresh(services):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=SAMPLE)

    cat, client = _catalog(services, handler)
    async with client:
        assert await cat.get("openai") is None
        assert await cat.get("anthropic") is None      # second miss while the first fetch is in flight
        await cat.schedule_refresh()                    # returns the in-flight task; awaiting it waits for the fetch
        assert calls == 1
        got = await cat.get("openai")
    assert got is not None and got.stale is False and got.models[0]["id"] == "gpt-5.5"


async def test_stale_row_is_served_now_and_refreshed_in_the_background(services):
    await _seed(services, "openai", [{"id": "old"}], timedelta(hours=25))
    cat, client = _catalog(services, _ok)
    async with client:
        got = await cat.get("openai")
        assert got is not None and got.stale is True and got.models == [{"id": "old"}]
        await cat.schedule_refresh()
        fresh = await cat.get("openai")
    assert fresh is not None and fresh.stale is False and fresh.models[0]["id"] == "gpt-5.5"


async def test_fresh_row_does_not_trigger_a_fetch(services):
    await _seed(services, "openai", [{"id": "fresh"}], timedelta(minutes=5))

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("fresh rows must not be refetched")

    cat, client = _catalog(services, never)
    async with client:
        got = await cat.get("openai")
        assert got is not None and got.stale is False
        assert cat._task is None                        # nothing was scheduled


def _refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused")


async def test_failed_fetch_keeps_existing_rows(services):
    await _seed(services, "openai", [{"id": "old"}], timedelta(hours=25))
    for handler in (
        lambda r: httpx.Response(500, text="nope"),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json=[]),      # not an object: normalize_catalog raises
        _refused,
    ):
        cat, client = _catalog(services, handler)
        async with client:
            assert await cat.refresh() is False
        assert (await _rows(services))["openai"].models == [{"id": "old"}]


async def test_unknown_provider_and_no_http_client(services):
    cat = ModelCatalog(services.session_factory, None)
    with pytest.raises(ValueError):
        await cat.get("xai")
    assert await cat.get("openai") is None          # no client: nothing to schedule, no error
    assert cat.schedule_refresh() is None
    await cat.close()                               # nothing running: a no-op
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest -q tests/test_model_catalog.py`
Expected: the six new tests FAIL with `ImportError: cannot import name 'ModelCatalog'`.

- [ ] **Step 3: Implement the service**

Add to the imports at the top of `backend/openbot/runtime/model_catalog.py`:

```python
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from openbot.db.models import ModelCatalogRow, utcnow
```

Add the constants next to `MODELS_DEV_URL`:

```python
CATALOG_TTL = timedelta(hours=24)
FETCH_TIMEOUT = 20.0
```

Append at the end of the module:

```python
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
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown must not raise
                pass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest -q tests/test_model_catalog.py`
Expected: 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/openbot/runtime/model_catalog.py backend/tests/test_model_catalog.py
git commit -m "feat(catalog): cache the model catalog in the database with background refresh

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `GET /api/v1/models` endpoint and app wiring

**Files:**
- Modify: `backend/openbot/api/schemas.py` (append after `SettingOut`, ~line 477)
- Create: `backend/openbot/api/models.py`
- Modify: `backend/openbot/services.py` (add a field)
- Modify: `backend/openbot/main.py` (`build_services` ~line 87, router list ~line 297, `start_background` ~line 121, `stop_background` ~line 152)
- Create: `backend/tests/test_models_api.py`

**Interfaces:**
- Consumes: `ModelCatalog`, `CatalogResult`, `CATALOG_PROVIDERS` (Tasks 2-3); `PROVIDER_MODELS` from `openbot.runtime.providers`.
- Produces: `CatalogModelOut`, `ModelsOut` pydantic models; `services.model_catalog: ModelCatalog | None`; route `GET /api/v1/models?provider=<id>` returning `ModelsOut`.

- [ ] **Step 1: Write the failing API tests**

Create `backend/tests/test_models_api.py`:

```python
import json
from pathlib import Path

from openbot.db.models import ModelCatalogRow, utcnow
from openbot.runtime.model_catalog import ModelCatalog, normalize_catalog
from openbot.runtime.providers import PROVIDER_MODELS

SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "models_dev_sample.json").read_text())


async def _seed(services, provider: str, models: list[dict]) -> None:
    async with services.session_factory() as s:
        s.add(ModelCatalogRow(provider=provider, models=models, fetched_at=utcnow()))
        await s.commit()


async def test_models_endpoint_falls_back_to_the_builtin_list_before_the_first_fetch(client):
    r = await client.get("/api/v1/models", params={"provider": "openai"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "openai" and body["source"] == "builtin" and body["stale"] is True and body["fetched_at"] is None
    assert [m["id"] for m in body["models"]] == PROVIDER_MODELS["openai"]
    first = body["models"][0]
    assert first["name"] == first["id"] and first["effort_levels"] == [] and first["cost_input"] is None and first["context"] is None


async def test_models_endpoint_serves_catalog_rows(client, services):
    services.model_catalog = ModelCatalog(services.session_factory, None)
    await _seed(services, "anthropic", normalize_catalog(SAMPLE)["anthropic"])
    body = (await client.get("/api/v1/models", params={"provider": "anthropic"})).json()
    assert body["source"] == "catalog" and body["stale"] is False and body["fetched_at"]
    assert body["models"][0]["id"] == "claude-opus-5-5"
    assert body["models"][0]["effort_levels"] == ["low", "medium", "high", "xhigh", "max"]
    assert body["models"][0]["cost_output"] == 25.0


async def test_models_endpoint_serves_an_empty_catalog_row_as_empty_not_builtin(client, services):
    services.model_catalog = ModelCatalog(services.session_factory, None)
    await _seed(services, "openrouter", [])
    body = (await client.get("/api/v1/models", params={"provider": "openrouter"})).json()
    assert body["source"] == "catalog" and body["models"] == []


async def test_models_endpoint_rejects_providers_without_a_catalog(client):
    for p in ("auto", "xai", "nope"):
        assert (await client.get("/api/v1/models", params={"provider": p})).status_code == 422, p
    assert (await client.get("/api/v1/models")).status_code == 422
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest -q tests/test_models_api.py`
Expected: FAIL (404 on `/api/v1/models`, and `AttributeError: model_catalog`).

- [ ] **Step 3: Add the response schemas**

Append to `backend/openbot/api/schemas.py` (`datetime` and `Literal` are already imported there):

```python
class CatalogModelOut(BaseModel):
    """One catalog row as the picker sees it; the builtin fallback fills only id and name."""
    id: str
    name: str
    family: str = ""
    description: str = ""
    reasoning: bool = False
    effort_levels: list[str] = []
    image_input: bool = False
    context: int | None = None
    output: int | None = None
    cost_input: float | None = None
    cost_output: float | None = None
    release_date: str = ""
    status: str | None = None


class ModelsOut(BaseModel):
    provider: str
    source: Literal["catalog", "builtin"]
    stale: bool
    fetched_at: datetime | None
    models: list[CatalogModelOut]
```

- [ ] **Step 4: Add the router**

Create `backend/openbot/api/models.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query

from openbot.api.deps import get_services
from openbot.api.schemas import ModelsOut
from openbot.runtime.model_catalog import CATALOG_PROVIDERS
from openbot.runtime.providers import PROVIDER_MODELS
from openbot.services import Services

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelsOut)
async def list_models(provider: str = Query(...), services: Services = Depends(get_services)):
    """One provider's catalog. Until the first fetch has landed (fresh install, offline) it is the builtin
    suggestion list, flagged `source: builtin`, so the picker always has something to show."""
    if provider not in CATALOG_PROVIDERS:
        raise HTTPException(422, f"no catalog for provider {provider!r}; one of {', '.join(CATALOG_PROVIDERS)}")
    catalog = services.model_catalog
    got = await catalog.get(provider) if catalog is not None else None
    if got is None:
        return ModelsOut(provider=provider, source="builtin", stale=True, fetched_at=None,
                         models=[{"id": m, "name": m} for m in PROVIDER_MODELS[provider]])
    return ModelsOut(provider=provider, source="catalog", stale=got.stale, fetched_at=got.fetched_at, models=got.models)
```

- [ ] **Step 5: Wire it into services and the app**

In `backend/openbot/services.py`, after the `http_client` field:

```python
    model_catalog: Any = None  # runtime.model_catalog.ModelCatalog (models.dev cache)
```

In `backend/openbot/main.py`:

1. Add to the `from openbot.api import (...)` block the name `models as models_api` (keep the block alphabetical like its neighbours), and add `from openbot.runtime.model_catalog import ModelCatalog`.
2. In `build_services`, right after `services.http_client = httpx.AsyncClient(timeout=15)`:

```python
    services.model_catalog = ModelCatalog(services.session_factory, services.http_client)
```

3. In the router tuple, add `models_api.router` after `providers.router`.
4. In `start_background`, after the `apply_stored_overrides` block at the top:

```python
    if services.model_catalog is not None:
        # First fetch (or a stale refresh) starts at boot, so the picker is populated by the first page load.
        await services.model_catalog.get("openrouter")
```

5. In `stop_background`, before the `services.reflector` block:

```python
    if services.model_catalog is not None:
        await services.model_catalog.close()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest -q tests/test_models_api.py tests/test_health.py tests/test_ollama_provider.py`
Expected: all PASS (the `client` fixture builds services without `model_catalog`, so the first test hits the builtin branch).

- [ ] **Step 7: Run the whole backend suite and ruff**

Run: `cd backend && uv run pytest -q && uv run ruff check .`
Expected: all PASS, no ruff findings.

- [ ] **Step 8: Commit**

```bash
git add backend/openbot/api/models.py backend/openbot/api/schemas.py backend/openbot/services.py backend/openbot/main.py backend/tests/test_models_api.py
git commit -m "feat(api): serve the model catalog at GET /models with a builtin fallback

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Effort at runtime for Anthropic and `reasoning_effort` validation

**Files:**
- Modify: `backend/openbot/runtime/providers.py:127-131` (the Anthropic branch of `provider_chat_model`)
- Modify: `backend/openbot/api/schemas.py:48-92` (`BotCreate`, `BotUpdate`)
- Test: `backend/tests/test_providers.py` (append), `backend/tests/test_bots_api.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `ChatAnthropic(..., reasoning_effort=<value>)` when `model_settings.reasoning_effort` is set; 422 from `POST/PATCH /bots` when `model_settings.reasoning_effort` is present but not a non-empty string.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_providers.py`:

```python
def test_reasoning_effort_passes_through_to_anthropic():
    """Same knob as the OpenAI-compatible path: ChatAnthropic maps it to output_config.effort."""
    m = chat_model(BotProfile(provider="anthropic", model="claude-opus-5-5", model_settings={"reasoning_effort": "low"}),
                   s(anthropic_api_key="k"))
    assert isinstance(m, ChatAnthropic) and m.reasoning_effort == "low"
    m = chat_model(BotProfile(provider="anthropic", model="claude-opus-5-5", model_settings={}), s(anthropic_api_key="k"))
    assert m.reasoning_effort is None
```

Append to `backend/tests/test_bots_api.py`:

```python
async def test_reasoning_effort_must_be_a_non_empty_string(client):
    assert (await client.post("/api/v1/bots", json={**BOT, "handle": "e1", "model_settings": {"reasoning_effort": 3}})).status_code == 422
    assert (await client.post("/api/v1/bots", json={**BOT, "handle": "e2", "model_settings": {"reasoning_effort": ""}})).status_code == 422
    r = await client.post("/api/v1/bots", json={**BOT, "handle": "e3", "model_settings": {"reasoning_effort": "low"}})
    assert r.status_code == 201, r.text
    assert r.json()["model_settings"] == {"reasoning_effort": "low"}
    assert (await client.patch(f"/api/v1/bots/{r.json()['id']}", json={"model_settings": {"reasoning_effort": []}})).status_code == 422
    r2 = await client.patch(f"/api/v1/bots/{r.json()['id']}", json={"model_settings": {}})
    assert r2.status_code == 200 and r2.json()["model_settings"] == {}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest -q tests/test_providers.py::test_reasoning_effort_passes_through_to_anthropic tests/test_bots_api.py::test_reasoning_effort_must_be_a_non_empty_string`
Expected: both FAIL (`reasoning_effort is None` for Anthropic; 201 instead of 422).

- [ ] **Step 3: Pass the effort to ChatAnthropic**

In `backend/openbot/runtime/providers.py`, change the Anthropic branch to:

```python
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs.setdefault("max_tokens", 8192)
        if "reasoning_effort" in ms:
            # Same knob as the OpenAI-compatible path below; ChatAnthropic maps it to output_config.effort.
            kwargs["reasoning_effort"] = ms["reasoning_effort"]
        return ChatAnthropic(model=model, api_key=key, **kwargs)
```

- [ ] **Step 4: Validate the setting on create and update**

In `backend/openbot/api/schemas.py`, above `class BotCreate`:

```python
def validate_model_settings(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Only the type is checked here: which effort values a model accepts is the provider's call, and a
    user may type a model the catalog does not know."""
    if value is not None and "reasoning_effort" in value:
        effort = value["reasoning_effort"]
        if not isinstance(effort, str) or not effort.strip():
            raise ValueError("model_settings.reasoning_effort must be a non-empty string")
    return value
```

Add to `BotCreate` (next to `validate_icon`):

```python
    @field_validator("model_settings")
    @classmethod
    def _model_settings(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_model_settings(value) or {}
```

Add to `BotUpdate`:

```python
    @field_validator("model_settings")
    @classmethod
    def _model_settings(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return validate_model_settings(value)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest -q tests/test_providers.py tests/test_bots_api.py`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/openbot/runtime/providers.py backend/openbot/api/schemas.py backend/tests/test_providers.py backend/tests/test_bots_api.py
git commit -m "feat(providers): pass reasoning_effort to Anthropic and validate its type

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Frontend types, client call and pure catalog helpers

**Files:**
- Modify: `frontend/src/api/types.ts` (append after `ProvidersOut`, line 27)
- Modify: `frontend/src/api/client.ts` (import list line 1; `Api` object, after `getProviders` ~line 99)
- Create: `frontend/src/lib/modelCatalog.ts`
- Create: `frontend/src/lib/modelCatalog.test.ts`

**Interfaces:**
- Produces (types): `CatalogModel`, `ModelsOut`; `Api.getModels(provider: string): Promise<ModelsOut>`.
- Produces (helpers, all pure): `CATALOG_PROVIDERS`, `hasCatalog(provider)`, `placeholderModel(id)`, `withSuggested(models, suggested)`, `filterModels(models, {text, reasoning, vision})`, `sortModels(models, "newest" | "cheapest")`, `groupModels(models, suggested, suggestedLabel, sort): ModelGroup[]`, `formatCost(m)`, `formatContext(n)`, `effortLevelsFor(models, id)`, `reconcileEffort(settings, models, id)`, `splitAutoDefault(s)`.

- [ ] **Step 1: Add the types and the client call**

Append to `frontend/src/api/types.ts`:

```ts
export interface CatalogModel { id: string; name: string; family: string; description: string; reasoning: boolean; effort_levels: string[]; image_input: boolean; context: number | null; output: number | null; cost_input: number | null; cost_output: number | null; release_date: string; status: string | null; }
export interface ModelsOut { provider: string; source: "catalog" | "builtin"; stale: boolean; fetched_at: string | null; models: CatalogModel[]; }
```

In `frontend/src/api/client.ts`: add `ModelsOut` to the type import on line 1, and after `getProviders` add:

```ts
  getModels: (provider: string) => api<ModelsOut>(`/models?provider=${encodeURIComponent(provider)}`),
```

- [ ] **Step 2: Write the failing helper tests**

Create `frontend/src/lib/modelCatalog.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { CatalogModel } from "../api/types";
import { effortLevelsFor, filterModels, formatContext, formatCost, groupModels, hasCatalog, reconcileEffort, sortModels, splitAutoDefault, withSuggested } from "./modelCatalog";

const model = (id: string, extra: Partial<CatalogModel> = {}): CatalogModel => ({
  id, name: id, family: "", description: "", reasoning: false, effort_levels: [], image_input: false, context: 200000, output: null,
  cost_input: 1, cost_output: 5, release_date: "2026-01-01", status: null, ...extra,
});
const opus = model("claude-opus-5-5", { name: "Claude Opus 5.5", family: "claude-opus", reasoning: true, effort_levels: ["low", "high"], image_input: true, cost_input: 5, cost_output: 25, release_date: "2026-03-01" });
const sonnet = model("claude-sonnet-4-5", { name: "Claude Sonnet 4.5", family: "claude-sonnet", reasoning: true, cost_input: 3, cost_output: 15, release_date: "2025-09-29" });
const haiku = model("claude-haiku-4-5", { name: "Claude Haiku 4.5", family: "claude-haiku", release_date: "2025-10-15" });
const older = model("claude-opus-4-5", { name: "Claude Opus 4.5", family: "claude-opus", reasoning: true, release_date: "2025-11-01" });
const all = [haiku, opus, sonnet, older];

describe("filterModels", () => {
  it("matches id, name and family case-insensitively and applies chips", () => {
    const ids = (ms: CatalogModel[]) => ms.map((m) => m.id);
    expect(ids(filterModels(all, { text: "", reasoning: false, vision: false }))).toEqual(ids(all));
    expect(ids(filterModels(all, { text: "Claude-Opus-5", reasoning: false, vision: false }))).toEqual(["claude-opus-5-5"]);
    expect(ids(filterModels(all, { text: "sonnet 4", reasoning: false, vision: false }))).toEqual([]);
    expect(ids(filterModels(all, { text: "HAIKU", reasoning: false, vision: false }))).toEqual(["claude-haiku-4-5"]);
    expect(ids(filterModels(all, { text: "", reasoning: true, vision: false }))).toEqual(["claude-opus-5-5", "claude-sonnet-4-5", "claude-opus-4-5"]);
    expect(ids(filterModels(all, { text: "", reasoning: true, vision: true }))).toEqual(["claude-opus-5-5"]);
  });
});

describe("sortModels and groupModels", () => {
  it("orders newest first by default and cheapest first on request, unknown cost last", () => {
    expect(sortModels(all, "newest").map((m) => m.id)).toEqual(["claude-opus-5-5", "claude-opus-4-5", "claude-haiku-4-5", "claude-sonnet-4-5"]);
    const free = model("free", { cost_input: 0, cost_output: 0 });
    const unknown = model("unknown", { cost_input: null, cost_output: null });
    expect(sortModels([opus, unknown, haiku, free], "cheapest").map((m) => m.id)).toEqual(["free", "claude-haiku-4-5", "claude-opus-5-5", "unknown"]);
  });
  it("groups by family in rank order with the suggested group pinned first and not repeated", () => {
    const groups = groupModels(all, ["claude-haiku-4-5"], "Suggested", "newest");
    expect(groups.map((g) => [g.label, g.models.map((m) => m.id)])).toEqual([
      ["Suggested", ["claude-haiku-4-5"]],
      ["claude-opus", ["claude-opus-5-5", "claude-opus-4-5"]],
      ["claude-sonnet", ["claude-sonnet-4-5"]],
    ]);
    expect(groupModels(all, [], "Suggested", "newest")[0].label).toBe("claude-opus");
    expect(groupModels([model("x")], [], "Suggested", "newest")[0].label).toBe("Other");
  });
  it("keeps an installed model the catalog does not know, with a bare name", () => {
    const merged = withSuggested([opus], ["qwen3:8b", "claude-opus-5-5"]);
    expect(merged.map((m) => m.id)).toEqual(["claude-opus-5-5", "qwen3:8b"]);
    const groups = groupModels(merged, ["qwen3:8b", "claude-opus-5-5"], "Installed", "newest");
    expect(groups[0].label).toBe("Installed");
    expect(groups[0].models.map((m) => [m.id, m.name, m.context])).toEqual([["qwen3:8b", "qwen3:8b", null], ["claude-opus-5-5", "Claude Opus 5.5", 200000]]);
    expect(groups).toHaveLength(1);
  });
});

describe("formatting", () => {
  it("formats cost per million tokens", () => {
    expect(formatCost({ cost_input: 1.25, cost_output: 10 })).toBe("$1.25 / $10 per M tokens");
    expect(formatCost({ cost_input: 0.003, cost_output: 0.5 })).toBe("$0.003 / $0.5 per M tokens");
    expect(formatCost({ cost_input: 0, cost_output: 0 })).toBe("free");
    expect(formatCost({ cost_input: null, cost_output: null })).toBe("");
    expect(formatCost({ cost_input: null, cost_output: 2 })).toBe("$? / $2 per M tokens");
  });
  it("formats context windows", () => {
    expect(formatContext(200000)).toBe("200k");
    expect(formatContext(131072)).toBe("131k");
    expect(formatContext(1048576)).toBe("1M");
    expect(formatContext(null)).toBe("");
  });
});

describe("effort helpers", () => {
  it("reads effort levels of a known model and nothing for unknown ones", () => {
    expect(effortLevelsFor(all, "claude-opus-5-5")).toEqual(["low", "high"]);
    expect(effortLevelsFor(all, "claude-haiku-4-5")).toEqual([]);
    expect(effortLevelsFor(all, "typed-by-hand")).toEqual([]);
    expect(effortLevelsFor(undefined, "claude-opus-5-5")).toEqual([]);
  });
  it("drops an effort the catalog says the model does not accept, keeps it for unknown models", () => {
    expect(reconcileEffort({ reasoning_effort: "high", web_search: true }, all, "claude-opus-5-5")).toEqual({ reasoning_effort: "high", web_search: true });
    expect(reconcileEffort({ reasoning_effort: "max", web_search: true }, all, "claude-opus-5-5")).toEqual({ web_search: true });
    expect(reconcileEffort({ reasoning_effort: "high" }, all, "claude-haiku-4-5")).toEqual({});
    expect(reconcileEffort({ reasoning_effort: "high" }, all, "typed-by-hand")).toEqual({ reasoning_effort: "high" });
    expect(reconcileEffort({ reasoning_effort: "high" }, undefined, "claude-haiku-4-5")).toEqual({ reasoning_effort: "high" });
  });
  it("splits the auto provider's resolved default and knows which providers have a catalog", () => {
    expect(splitAutoDefault("openrouter/anthropic/claude-sonnet-5")).toEqual({ provider: "openrouter", model: "anthropic/claude-sonnet-5" });
    expect(splitAutoDefault("")).toBeNull();
    expect(splitAutoDefault(undefined)).toBeNull();
    expect(hasCatalog("ollama")).toBe(true);
    expect(hasCatalog("xai")).toBe(false);
  });
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/lib/modelCatalog.test.ts`
Expected: FAIL (cannot resolve `./modelCatalog`).

- [ ] **Step 4: Write the helpers**

Create `frontend/src/lib/modelCatalog.ts`:

```ts
import type { CatalogModel } from "../api/types";

/** Providers the backend serves a models.dev catalog for (GET /models). xAI keeps its builtin list. */
export const CATALOG_PROVIDERS = new Set(["openai", "anthropic", "openrouter", "ollama"]);
export const hasCatalog = (provider: string): boolean => CATALOG_PROVIDERS.has(provider);

export interface ModelFilters { text: string; reasoning: boolean; vision: boolean }
export type ModelSort = "newest" | "cheapest";
export interface ModelGroup { label: string; models: CatalogModel[] }

/** A bare row for an id the catalog does not know: an installed Ollama tag, or the configured default. */
export function placeholderModel(id: string): CatalogModel {
  return { id, name: id, family: "", description: "", reasoning: false, effort_levels: [], image_input: false, context: null, output: null, cost_input: null, cost_output: null, release_date: "", status: null };
}

/** The catalog plus a placeholder for every suggested id it does not know, so those still list and pin. */
export function withSuggested(models: CatalogModel[], suggested: string[]): CatalogModel[] {
  const known = new Set(models.map((m) => m.id));
  return [...models, ...suggested.filter((id) => !known.has(id)).map(placeholderModel)];
}

/** Case-insensitive substring match on id, name and family; the chips narrow further. */
export function filterModels(models: CatalogModel[], f: ModelFilters): CatalogModel[] {
  const q = f.text.trim().toLowerCase();
  return models.filter((m) =>
    (!q || m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q) || m.family.toLowerCase().includes(q))
    && (!f.reasoning || m.reasoning) && (!f.vision || m.image_input));
}

const byNewest = (a: CatalogModel, b: CatalogModel) => b.release_date.localeCompare(a.release_date) || a.id.localeCompare(b.id);
const byCheapest = (a: CatalogModel, b: CatalogModel) => {
  const ca = a.cost_output ?? Number.POSITIVE_INFINITY, cb = b.cost_output ?? Number.POSITIVE_INFINITY;
  if (ca === cb) return byNewest(a, b);
  return ca - cb;
};
export function sortModels(models: CatalogModel[], sort: ModelSort): CatalogModel[] {
  return [...models].sort(sort === "cheapest" ? byCheapest : byNewest);
}

/** Pinned group first (suggested ids in their given order, only those present in `models`), then one
 *  group per family, families in the order their best-ranked model appears under `sort`. */
export function groupModels(models: CatalogModel[], suggested: string[], suggestedLabel: string, sort: ModelSort): ModelGroup[] {
  const sorted = sortModels(models, sort);
  const byId = new Map(sorted.map((m) => [m.id, m]));
  const pinned = suggested.flatMap((id) => { const m = byId.get(id); return m ? [m] : []; });
  const pinnedIds = new Set(pinned.map((m) => m.id));
  const groups: ModelGroup[] = pinned.length ? [{ label: suggestedLabel, models: pinned }] : [];
  const families = new Map<string, CatalogModel[]>();
  for (const m of sorted) {
    if (pinnedIds.has(m.id)) continue;
    const label = m.family || "Other";
    const g = families.get(label);
    if (g) g.push(m); else families.set(label, [m]);
  }
  for (const [label, ms] of families) groups.push({ label, models: ms });
  return groups;
}

/** Up to two decimals, trailing zeros dropped; sub-cent prices keep one significant digit ($0.003). */
const money = (n: number): string => (n > 0 && n < 0.01 ? Number(n.toPrecision(1)).toString() : Number(n.toFixed(2)).toString());

/** "$1.25 / $10 per M tokens" (input / output); "free" when both are zero; "" when both are unknown. */
export function formatCost(m: Pick<CatalogModel, "cost_input" | "cost_output">): string {
  if (m.cost_input == null && m.cost_output == null) return "";
  if ((m.cost_input ?? 0) === 0 && (m.cost_output ?? 0) === 0) return "free";
  const part = (v: number | null) => (v == null ? "$?" : `$${money(v)}`);
  return `${part(m.cost_input)} / ${part(m.cost_output)} per M tokens`;
}

/** 200000 -> "200k", 1048576 -> "1M". */
export function formatContext(n: number | null): string {
  if (n == null) return "";
  if (n >= 1_000_000) return `${Number((n / 1_000_000).toPrecision(2))}M`;
  return `${Math.round(n / 1000)}k`;
}

/** Effort levels the catalog declares for `modelId`; [] when unknown or not effort-capable. */
export function effortLevelsFor(models: CatalogModel[] | undefined, modelId: string): string[] {
  return models?.find((m) => m.id === modelId)?.effort_levels ?? [];
}

/** model_settings without a reasoning_effort the catalog says this model does not accept. A model the
 *  catalog does not know (typed by hand, or a catalog that has not loaded) keeps whatever is set: the
 *  provider is the authority there. */
export function reconcileEffort(settings: Record<string, unknown>, models: CatalogModel[] | undefined, modelId: string): Record<string, unknown> {
  const effort = settings.reasoning_effort;
  const m = models?.find((x) => x.id === modelId);
  if (typeof effort !== "string" || !m || m.effort_levels.includes(effort)) return settings;
  const { reasoning_effort: _dropped, ...rest } = settings;
  return rest;
}

/** The provider and model an "auto" bot resolves to, from /providers' `default_model` ("<provider>/<model>"). */
export function splitAutoDefault(autoDefaultModel: string | undefined): { provider: string; model: string } | null {
  if (!autoDefaultModel) return null;
  const i = autoDefaultModel.indexOf("/");
  return i < 0 ? null : { provider: autoDefaultModel.slice(0, i), model: autoDefaultModel.slice(i + 1) };
}
```

- [ ] **Step 5: Run the tests, typecheck and lint**

Run: `cd frontend && pnpm exec vitest run src/lib/modelCatalog.test.ts && pnpm typecheck && pnpm lint`
Expected: all PASS, no type or lint errors. If oxlint flags the unused `_dropped` binding, rename to `reasoning_effort: _` or use `delete` on a copy.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/lib/modelCatalog.ts frontend/src/lib/modelCatalog.test.ts
git commit -m "feat(frontend): model catalog types, client call and picker helpers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `ModelPicker` combobox component

**Files:**
- Create: `frontend/src/components/ModelPicker.tsx`
- Create: `frontend/src/components/ModelPicker.test.tsx`

**Interfaces:**
- Consumes: `Api.getModels`, helpers from Task 6, `Input`, `Badge`, `Spinner` from `components/ui`.
- Produces: `export function ModelPicker(props: ModelPickerProps)` with `ModelPickerProps = { provider: string; value: string; onChange: (v: string) => void; suggested?: string[]; suggestedLabel?: string; id?: string; required?: boolean; className?: string }`. The input has `role="combobox"`; the panel `role="listbox"` with `role="option"` rows whose first `<span>` is the model id.

- [ ] **Step 1: Write the failing component tests**

Create `frontend/src/components/ModelPicker.test.tsx`:

```tsx
// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Api } from "../api/client";
import type { CatalogModel, ModelsOut } from "../api/types";
import { ModelPicker } from "./ModelPicker";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const model = (id: string, extra: Partial<CatalogModel> = {}): CatalogModel => ({
  id, name: id, family: "", description: "", reasoning: false, effort_levels: [], image_input: false, context: 200000, output: null,
  cost_input: 1, cost_output: 5, release_date: "2026-01-01", status: null, ...extra,
});
const catalog: ModelsOut = { provider: "anthropic", source: "catalog", stale: false, fetched_at: "2026-09-27T00:00:00Z", models: [
  model("claude-opus-5-5", { name: "Claude Opus 5.5", family: "claude-opus", description: "Most capable", reasoning: true, effort_levels: ["low", "high"], image_input: true, cost_input: 5, cost_output: 25, release_date: "2026-03-01" }),
  model("claude-haiku-4-5", { name: "Claude Haiku 4.5", family: "claude-haiku", release_date: "2025-10-15" }),
] };

let root: Root; let el: HTMLDivElement; let qc: QueryClient; let last = "";
function Host({ initial = "", suggested = [] as string[], provider = "anthropic", suggestedLabel = "Suggested" }) {
  const [v, setV] = useState(initial);
  last = v;
  return <ModelPicker provider={provider} value={v} onChange={setV} suggested={suggested} suggestedLabel={suggestedLabel} />;
}
async function show(props: Parameters<typeof Host>[0] = {}) {
  await act(async () => root.render(<QueryClientProvider client={qc}><Host {...props} /></QueryClientProvider>));
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
}
const input = () => el.querySelector<HTMLInputElement>("input[role=combobox]")!;
const options = () => [...el.querySelectorAll<HTMLElement>("[role=option]")].map((o) => o.querySelector("span")!.textContent);
const groupLabels = () => [...el.querySelectorAll<HTMLElement>("[data-group]")].map((g) => g.dataset.group);
// jsdom fires no focus event on an element that already has focus, so blur first to reopen the panel.
const focus = () => act(async () => { input().blur(); input().focus(); });
async function type(text: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input(), text);
    input().dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const key = (k: string) => act(async () => { input().dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true })); });
const press = (elm: Element) => act(async () => { elm.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true })); elm.dispatchEvent(new MouseEvent("click", { bubbles: true })); });

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(Api, "getModels").mockResolvedValue(catalog);
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(async () => { await act(async () => root.unmount()); el.remove(); qc.clear(); vi.restoreAllMocks(); });

it("opens on focus, lists the catalog grouped by family newest first, and filters as you type", async () => {
  await show();
  expect(el.querySelector("[role=listbox]")).toBeNull();
  await focus();
  expect(options()).toEqual(["claude-opus-5-5", "claude-haiku-4-5"]);
  expect(groupLabels()).toEqual(["claude-opus", "claude-haiku"]);
  await type("HAIKU");
  expect(options()).toEqual(["claude-haiku-4-5"]);
  expect(last).toBe("HAIKU");
});

it("keeps free text as the value and notes it is not in the catalog", async () => {
  await show();
  await focus();
  await type("my-custom-model");
  expect(last).toBe("my-custom-model");
  expect(options()).toEqual([]);
  expect(el.textContent).toContain("No matching models");
  expect(el.textContent).toContain("Not in the catalog");
  await type("claude-opus-5-5");
  expect(el.textContent).not.toContain("Not in the catalog");
});

it("picks with the keyboard and closes; Escape closes without picking", async () => {
  await show();
  await focus();
  await key("ArrowDown");
  await key("Enter");
  expect(last).toBe("claude-haiku-4-5");
  expect(el.querySelector("[role=listbox]")).toBeNull();
  await focus();
  await key("Escape");
  expect(el.querySelector("[role=listbox]")).toBeNull();
  expect(last).toBe("claude-haiku-4-5");
});

it("picks with the mouse, shows cost and badges, and the chips narrow the list", async () => {
  await show();
  await focus();
  const opus = el.querySelectorAll("[role=option]")[0];
  expect(opus.textContent).toContain("$5 / $25 per M tokens");
  expect(opus.textContent).toContain("effort");
  expect(opus.textContent).toContain("200k");
  expect(opus.textContent).toContain("Most capable");
  await press(el.querySelector("button[aria-pressed][data-chip=reasoning]")!);
  expect(options()).toEqual(["claude-opus-5-5"]);
  await press(el.querySelectorAll("[role=option]")[0]);
  expect(last).toBe("claude-opus-5-5");
});

it("pins suggested ids first under the given label and marks Ollama rows that are not installed", async () => {
  await show({ provider: "ollama", suggested: ["qwen3:8b", "claude-haiku-4-5"], suggestedLabel: "Installed" });
  await focus();
  expect(groupLabels()[0]).toBe("Installed");
  expect(options()).toEqual(["qwen3:8b", "claude-haiku-4-5", "claude-opus-5-5"]);
  const rows = el.querySelectorAll("[role=option]");
  expect(rows[0].textContent).not.toContain("not installed");
  expect(rows[1].textContent).toContain("on Ollama Cloud");
  expect(rows[2].textContent).toContain("not installed");
});

it("shows the updating hint when the catalog is stale or builtin", async () => {
  vi.mocked(Api.getModels).mockResolvedValue({ ...catalog, source: "builtin", stale: true, fetched_at: null, models: [model("gpt-5.5", { context: null, cost_input: null, cost_output: null })] });
  await show();
  await focus();
  expect(el.textContent).toContain("Catalog updating");
  expect(options()).toEqual(["gpt-5.5"]);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/components/ModelPicker.test.tsx`
Expected: FAIL (cannot resolve `./ModelPicker`).

- [ ] **Step 3: Write the component**

Create `frontend/src/components/ModelPicker.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { useId, useMemo, useState } from "react";
import { Api } from "../api/client";
import type { CatalogModel } from "../api/types";
import { filterModels, formatContext, formatCost, groupModels, withSuggested, type ModelSort } from "../lib/modelCatalog";
import { Badge, Input, Spinner } from "./ui";

export interface ModelPickerProps {
  provider: string;
  value: string;
  onChange: (value: string) => void;
  /** Ids to pin at the top: the server's short suggestion list, or the installed models for Ollama. */
  suggested?: string[];
  suggestedLabel?: string;
  id?: string;
  required?: boolean;
  className?: string;
}

const Chip = ({ on, name, onToggle, children }: { on: boolean; name: string; onToggle: () => void; children: React.ReactNode }) => (
  <button type="button" aria-pressed={on} data-chip={name} onMouseDown={(e) => e.preventDefault()} onClick={onToggle}
    className={`rounded-ui border px-1.5 py-0.5 text-[11px] transition-colors ${on ? "border-accent bg-accent/10 text-fg" : "border-line text-muted hover:text-fg"}`}>
    {children}
  </button>
);

/** A combobox over the provider's catalog. The text is the value: anything typed is sent as the model id,
 *  whether or not the catalog knows it. Rows are grouped by family; typing filters on id, name and family. */
export function ModelPicker({ provider, value, onChange, suggested = [], suggestedLabel = "Suggested", id, required, className = "" }: ModelPickerProps) {
  const models = useQuery({ queryKey: ["models", provider], queryFn: () => Api.getModels(provider), staleTime: 5 * 60_000 });
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const [reasoning, setReasoning] = useState(false);
  const [vision, setVision] = useState(false);
  const [sort, setSort] = useState<ModelSort>("newest");
  const listId = useId();
  const all = useMemo(() => withSuggested(models.data?.models ?? [], suggested), [models.data, suggested]);
  const groups = useMemo(() => groupModels(filterModels(all, { text: value, reasoning, vision }), suggested, suggestedLabel, sort),
    [all, value, reasoning, vision, sort, suggested, suggestedLabel]);
  const flat = useMemo(() => groups.flatMap((g) => g.models), [groups]);
  const highlight = Math.min(sel, Math.max(flat.length - 1, 0));
  const known = value === "" || all.some((m) => m.id === value);
  const installed = provider === "ollama" ? new Set(suggested) : null;
  const pick = (m: CatalogModel) => { onChange(m.id); setOpen(false); };

  return (
    <div className="relative">
      <Input role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list" autoComplete="off" spellCheck={false}
        id={id} required={required} value={value} className={`font-mono ${className}`}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setSel(0); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (!open) { if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); } return; }
          if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, flat.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
          else if (e.key === "Enter") { if (flat[highlight]) { e.preventDefault(); pick(flat[highlight]); } }
          else if (e.key === "Escape" || e.key === "Tab") { setOpen(false); }
        }} />
      {!known && !models.isLoading && <div className="mt-1 font-sans text-[11px] text-faint">Not in the catalog; sent to the provider as typed.</div>}
      {open && (
        <div id={listId} role="listbox" aria-label="Models"
          className="absolute left-0 right-0 top-full z-10 mt-1 max-h-80 overflow-y-auto rounded-ui border border-line bg-surface py-1 shadow-[0_12px_32px_-12px_rgb(0_0_0/0.45)]">
          <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-2 pb-1.5 pt-1 font-sans text-[11px] text-faint">
            <Chip on={reasoning} name="reasoning" onToggle={() => setReasoning((v) => !v)}>Reasoning</Chip>
            <Chip on={vision} name="vision" onToggle={() => setVision((v) => !v)}>Vision</Chip>
            <button type="button" data-sort={sort} onMouseDown={(e) => e.preventDefault()} onClick={() => setSort((s) => (s === "newest" ? "cheapest" : "newest"))}
              className="ml-auto underline underline-offset-2 hover:text-fg">
              {sort === "newest" ? "newest first" : "cheapest first"}
            </button>
            {(models.data?.stale ?? false) && <span>Catalog updating…</span>}
          </div>
          {models.isLoading && <div className="px-3 py-2"><Spinner /></div>}
          {!models.isLoading && flat.length === 0 && <div className="px-3 py-2 font-sans text-[13px] text-muted">No matching models.</div>}
          {groups.map((g) => (
            <div key={g.label} data-group={g.label}>
              <div className="px-3 pb-0.5 pt-2 font-sans text-[11px] font-medium uppercase tracking-wide text-faint">{g.label}</div>
              {g.models.map((m) => {
                const i = flat.indexOf(m);
                const cost = formatCost(m);
                return (
                  <div key={m.id} role="option" aria-selected={i === highlight} onMouseDown={(e) => { e.preventDefault(); pick(m); }} onMouseEnter={() => setSel(i)}
                    className={`cursor-pointer px-3 py-1.5 ${i === highlight ? "bg-sunken" : ""}`}>
                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <span className="font-mono text-[13px] text-fg">{m.id}</span>
                      {m.name !== m.id && <span className="font-sans text-xs text-muted">{m.name}</span>}
                      {cost && <span className="font-sans text-xs text-faint">{cost}{provider === "ollama" ? " on Ollama Cloud" : ""}</span>}
                      {installed && !installed.has(m.id) && <span className="font-sans text-xs text-faint">not installed</span>}
                    </div>
                    {(m.reasoning || m.effort_levels.length > 0 || m.image_input || m.context != null || m.status === "beta") && (
                      <div className="mt-0.5 flex flex-wrap gap-x-2">
                        {m.reasoning && <Badge>reasoning</Badge>}
                        {m.effort_levels.length > 0 && <Badge tone="green">effort</Badge>}
                        {m.image_input && <Badge>vision</Badge>}
                        {m.context != null && <Badge>{formatContext(m.context)}</Badge>}
                        {m.status === "beta" && <Badge tone="amber">beta</Badge>}
                      </div>
                    )}
                    {m.description && <div className="mt-0.5 font-sans text-xs text-faint">{m.description}</div>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests, typecheck and lint**

Run: `cd frontend && pnpm exec vitest run src/components/ModelPicker.test.tsx && pnpm typecheck && pnpm lint`
Expected: 6 PASS, no type or lint errors. If `React.ReactNode` is not in scope for `Chip`, import `type ReactNode` from `react` and use it.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ModelPicker.tsx frontend/src/components/ModelPicker.test.tsx
git commit -m "feat(frontend): ModelPicker combobox over the model catalog

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Bot editor: picker, Effort select and rerouting warning

**Files:**
- Modify: `frontend/src/pages/BotEditorPage.tsx` (imports lines 1-11; save mutation ~line 50; model section lines 135-162)
- Test: `frontend/src/pages/BotEditorPage.test.tsx` (append; extend `beforeEach`)

**Interfaces:**
- Consumes: `ModelPicker` (Task 7); `hasCatalog`, `effortLevelsFor`, `reconcileEffort`, `splitAutoDefault` (Task 6); `Api.getModels`.
- Produces: the bot editor's Model field uses `ModelPicker` for catalog providers; an `Effort` `<select aria-label="Effort">` appears only when the effective model declares effort levels; the save payload's `model_settings` passes through `reconcileEffort`.

- [ ] **Step 1: Write the failing editor tests**

In `frontend/src/pages/BotEditorPage.test.tsx`:

Add to the imports: `import type { Bot, CatalogModel, ModelsOut, ProvidersOut } from "../api/types";` (replace the existing `Bot` import line).

Add after the `bot` helper:

```tsx
const model = (id: string, extra: Partial<CatalogModel> = {}): CatalogModel => ({
  id, name: id, family: "", description: "", reasoning: false, effort_levels: [], image_input: false, context: 200000, output: null,
  cost_input: 1, cost_output: 5, release_date: "2026-01-01", status: null, ...extra,
});
const catalog: ModelsOut = { provider: "anthropic", source: "catalog", stale: false, fetched_at: "2026-09-27T00:00:00Z", models: [
  model("claude-opus-5-5", { family: "claude-opus", reasoning: true, effort_levels: ["low", "high"] }),
  model("claude-haiku-4-5", { family: "claude-haiku" }),
] };
const providers: ProvidersOut = { embedding_model: "none", embeddings_configured: false, providers: [
  { id: "auto", configured: true, models: [], default_model: "anthropic/claude-opus-5-5" },
  { id: "anthropic", configured: true, models: ["claude-opus-5-5"], default_model: "claude-opus-5-5" },
  { id: "openrouter", configured: false, models: [], default_model: "" },
] };
const effortSelect = () => el.querySelector<HTMLSelectElement>("select[aria-label=Effort]");
const submit = () => act(async () => { el.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); await new Promise((r) => setTimeout(r, 20)); });
```

In `beforeEach`, add: `vi.spyOn(Api, "getModels").mockResolvedValue(catalog);`

Append the tests:

```tsx
it("offers effort levels only for models that declare them, including the auto provider's resolved model", async () => {
  vi.mocked(Api.getProviders).mockResolvedValue(providers);
  vi.spyOn(Api, "getBot").mockImplementation((id: string) => Promise.resolve(
    id === "b1" ? { ...bot("b1", "Opus"), provider: "anthropic", model: "claude-opus-5-5", model_settings: { reasoning_effort: "high" } }
    : id === "b2" ? { ...bot("b2", "Haiku"), provider: "anthropic", model: "claude-haiku-4-5" }
    : { ...bot("b3", "Auto"), provider: "auto", model: "" }));
  await show("/edit/b1");
  await until(() => effortSelect() !== null);
  expect([...effortSelect()!.options].map((o) => o.value)).toEqual(["", "low", "high"]);
  expect(effortSelect()!.value).toBe("high");

  await show("/edit/b2");
  await until(() => nameInput() === "Haiku");
  expect(effortSelect()).toBeNull();

  await show("/edit/b3");
  await until(() => nameInput() === "Auto");
  await until(() => effortSelect() !== null);
  expect(effortSelect()!.value).toBe("");
});

it("drops an effort the model does not accept on save and removes the key when Default is chosen", async () => {
  vi.mocked(Api.getProviders).mockResolvedValue(providers);
  vi.spyOn(Api, "getBot").mockResolvedValue({ ...bot("b1", "Stale"), provider: "anthropic", model: "claude-haiku-4-5", model_settings: { reasoning_effort: "high", web_search: true } });
  const update = vi.spyOn(Api, "updateBot").mockImplementation(async (id, b) => ({ ...bot(id, "Stale"), ...b } as Bot));
  await show("/edit/b1");
  await until(() => nameInput() === "Stale");
  await until(() => vi.mocked(Api.getModels).mock.calls.length > 0);
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  await submit();
  expect(update.mock.calls[0][1].model_settings).toEqual({ web_search: true });

  vi.spyOn(Api, "getBot").mockResolvedValue({ ...bot("b2", "Opus"), provider: "anthropic", model: "claude-opus-5-5", model_settings: { reasoning_effort: "low" } });
  await show("/edit/b2");
  await until(() => effortSelect() !== null && effortSelect()!.value === "low");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(effortSelect()!, "");
    effortSelect()!.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await submit();
  expect(update.mock.calls[1][1].model_settings).toEqual({});
});

it("uses the catalog picker for catalog providers and warns when OpenRouter reroutes cloud bots", async () => {
  vi.mocked(Api.getProviders).mockResolvedValue({ ...providers, providers: providers.providers.map((p) => (p.id === "openrouter" ? { ...p, configured: true } : p)) });
  vi.spyOn(Api, "getBot").mockResolvedValue({ ...bot("b1", "Opus"), provider: "anthropic", model: "claude-opus-5-5" });
  await show("/edit/b1");
  await until(() => el.querySelector("input[role=combobox]") !== null);
  expect(el.querySelector<HTMLInputElement>("input[role=combobox]")!.value).toBe("claude-opus-5-5");
  expect(el.textContent).toContain("With an OpenRouter key configured");
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/pages/BotEditorPage.test.tsx`
Expected: the three new tests FAIL (no effort select, no combobox, no warning); the existing test still passes.

- [ ] **Step 3: Integrate the picker and the Effort select**

In `frontend/src/pages/BotEditorPage.tsx`:

1. Add imports:

```tsx
import { ModelPicker } from "../components/ModelPicker";
import { effortLevelsFor, hasCatalog, reconcileEffort, splitAutoDefault } from "../lib/modelCatalog";
```

2. After `const prov = providers.data?.providers.find((p) => p.id === form.provider);` add:

```tsx
  // The model whose effort levels apply: the bot's own, or for "auto" whatever the server resolves to.
  const autoTarget = isAuto ? splitAutoDefault(auto?.default_model) : null;
  const effortProvider = isAuto ? autoTarget?.provider : form.provider;
  const effortModel = isAuto ? autoTarget?.model ?? "" : form.model;
  const effortCatalog = useQuery({
    queryKey: ["models", effortProvider], queryFn: () => Api.getModels(effortProvider!),
    enabled: !!effortProvider && hasCatalog(effortProvider), staleTime: 5 * 60_000,
  });
  const effortLevels = effortLevelsFor(effortCatalog.data?.models, effortModel);
  const effort = typeof form.model_settings.reasoning_effort === "string" ? form.model_settings.reasoning_effort : "";
  const setEffort = (v: string) => {
    const { reasoning_effort: _current, ...rest } = form.model_settings;
    set("model_settings", v ? { ...rest, reasoning_effort: v } : rest);
  };
  // effective_bot_profile sends every non-Ollama bot to the default OpenRouter model once that key exists.
  const rerouted = !isAuto && form.provider !== "ollama" && (providers.data?.providers.find((p) => p.id === "openrouter")?.configured ?? false);
```

   (`useQuery` is already imported. These hooks must sit above the early `if (!isNew && bot.isLoading) return <Spinner />;` line, which is why they go next to `prov`.)

3. In the save mutation, replace the `payload` line with:

```tsx
      const payload = {
        ...form,
        approval_tools: form.approval_tools.filter((t) => form.tool_names.includes(t)),
        model_settings: reconcileEffort(form.model_settings, effortCatalog.data?.models, effortModel),
      };
```

4. Replace the non-auto Model field (the `<Input list="models" …>` + `<datalist>` block) with:

```tsx
        ) : hasCatalog(form.provider) ? (
          <Field label="Model" hint="Pick from the catalog or type any model id.">
            <ModelPicker provider={form.provider} value={form.model} onChange={(v) => set("model", v)}
              suggested={prov?.models ?? []} suggestedLabel={form.provider === "ollama" ? "Installed" : "Suggested"} required />
          </Field>
        ) : (
          <Field label="Model" hint="Pick from the list or type any model id.">
            <Input list="models" value={form.model} onChange={(e) => set("model", e.target.value)} required />
            <datalist id="models">{prov?.models.map((m) => <option key={m} value={m} />)}</datalist>
          </Field>
        )}
```

5. Right after that `)}` (before the `<div className="space-y-2 sm:col-span-2">` toggles), add:

```tsx
        {effortLevels.length > 0 && (
          <Field label="Effort" hint="How much reasoning the model spends per step. Default lets the provider decide.">
            <Select aria-label="Effort" value={effortLevels.includes(effort) ? effort : ""} onChange={(e) => setEffort(e.target.value)}>
              <option value="">Default (provider decides)</option>
              {effortLevels.map((l) => <option key={l} value={l}>{l}</option>)}
            </Select>
          </Field>
        )}
        {rerouted && (
          <Hint className="text-xs text-warn sm:col-span-2">
            With an OpenRouter key configured, cloud bots run on the default OpenRouter model from Settings. This model is saved but not used until that key is removed.
          </Hint>
        )}
```

- [ ] **Step 4: Run the editor tests, then the whole frontend suite, typecheck and lint**

Run: `cd frontend && pnpm exec vitest run src/pages/BotEditorPage.test.tsx && pnpm test && pnpm typecheck && pnpm lint`
Expected: all PASS. If oxlint complains about the unused `_current` binding, replace the destructuring with `const rest = { ...form.model_settings }; delete rest.reasoning_effort;`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/BotEditorPage.tsx frontend/src/pages/BotEditorPage.test.tsx
git commit -m "feat(frontend): catalog picker and effort level in the bot editor

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Settings page: picker for the default bot model

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx` (imports; `SettingsGroupCard` item rendering ~lines 228-242)
- Create: `frontend/src/pages/SettingsPage.test.tsx`

**Interfaces:**
- Consumes: `ModelPicker` (Task 7).
- Produces: the `bot_model` tunable renders `<ModelPicker provider="openrouter">` inside the generic settings card; drafts, Save and reset are unchanged.

- [ ] **Step 1: Write the failing settings test**

Create `frontend/src/pages/SettingsPage.test.tsx`:

```tsx
// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Api } from "../api/client";
import type { AppSetting } from "../api/types";
import SettingsPage from "./SettingsPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root; let el: HTMLDivElement; let qc: QueryClient;
const setting = (key: string, value: unknown, extra: Partial<AppSetting> = {}): AppSetting => ({
  key, group: "Model routing", label: key, description: "", type: "str", value, default: value, overridden: false, secret: false, is_set: true, ...extra,
});
const settings = [setting("bot_model", "openai/gpt-4o-mini"), setting("openrouter_provider_order", "")];
async function tick() { await act(async () => { await new Promise((r) => setTimeout(r, 20)); }); }
async function until(condition: () => boolean) {
  const deadline = Date.now() + 2000;
  while (!condition()) { if (Date.now() > deadline) throw new Error("Timed out"); await tick(); }
}
const combobox = () => el.querySelector<HTMLInputElement>("input[role=combobox]");
/** The Save button of the card that holds `node` (the API-key card has its own, always-enabled Save). */
function saveButtonFor(node: Element): HTMLButtonElement {
  for (let n: Element | null = node; n; n = n.parentElement) {
    const b = [...n.querySelectorAll("button")].find((x) => x.textContent === "Save");
    if (b) return b;
  }
  throw new Error("no Save button above the picker");
}

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(Api, "getSettings").mockResolvedValue(settings);
  vi.spyOn(Api, "getProviders").mockResolvedValue({ providers: [], embedding_model: "none", embeddings_configured: false });
  vi.spyOn(Api, "listTools").mockResolvedValue({ tools: [], errors: [] });
  vi.spyOn(Api, "listActors").mockResolvedValue([]);
  vi.spyOn(Api, "listMcpServers").mockResolvedValue([]);
  vi.spyOn(Api, "listMcpCatalog").mockResolvedValue([]);
  vi.spyOn(Api, "getDatabaseLocation").mockResolvedValue({ location: "/tmp" });
  vi.spyOn(Api, "getModels").mockResolvedValue({ provider: "openrouter", source: "catalog", stale: false, fetched_at: "2026-09-27T00:00:00Z", models: [
    { id: "z-ai/glm-5.3-flash", name: "GLM 5.3 Flash", family: "glm-flash", description: "", reasoning: true, effort_levels: ["low", "high"], image_input: false, context: 200000, output: null, cost_input: 0.1, cost_output: 0.3, release_date: "2026-04-01", status: null },
  ] });
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(async () => { await act(async () => root.unmount()); el.remove(); qc.clear(); vi.restoreAllMocks(); });

it("renders the default bot model as an OpenRouter catalog picker and saves the picked value", async () => {
  const patch = vi.spyOn(Api, "patchSettings").mockImplementation(async (updates) => settings.map((s) => (s.key in updates ? { ...s, value: updates[s.key], overridden: true } : s)));
  await act(async () => root.render(<QueryClientProvider client={qc}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>));
  await until(() => combobox() !== null);
  expect(combobox()!.value).toBe("openai/gpt-4o-mini");
  expect(Api.getModels).toHaveBeenCalledWith("openrouter");

  await act(async () => { combobox()!.blur(); combobox()!.focus(); });
  await until(() => el.querySelector("[role=option]") !== null);
  await act(async () => { el.querySelector("[role=option]")!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true })); });
  expect(combobox()!.value).toBe("z-ai/glm-5.3-flash");
  const save = saveButtonFor(combobox()!);
  expect(save.disabled).toBe(false);
  await act(async () => { save.click(); });
  await until(() => patch.mock.calls.length > 0);
  expect(patch.mock.calls[0][0]).toEqual({ bot_model: "z-ai/glm-5.3-flash" });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/pages/SettingsPage.test.tsx`
Expected: FAIL (no `input[role=combobox]`). If it fails earlier because `SettingsPage` calls an `Api` method not mocked here, add a `vi.spyOn(Api, "<name>")` for it in `beforeEach` (the list above covers every query the page issues at mount time as of this plan).

- [ ] **Step 3: Render the picker for `bot_model`**

In `frontend/src/pages/SettingsPage.tsx`:

1. Add `import { ModelPicker } from "../components/ModelPicker";`.
2. In `SettingsGroupCard`, in the item rendering, insert a branch before the final generic `<Input …>` branch:

```tsx
                ) : item.key === "bot_model" ? (
                  <div className="w-full">
                    <ModelPicker provider="openrouter" value={draft} onChange={setDraft} className={edited ? "border-warn" : ""} />
                  </div>
                ) : (
```

- [ ] **Step 4: Run the test, then the whole frontend suite, typecheck and lint**

Run: `cd frontend && pnpm exec vitest run src/pages/SettingsPage.test.tsx && pnpm test && pnpm typecheck && pnpm lint`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx frontend/src/pages/SettingsPage.test.tsx
git commit -m "feat(frontend): pick the default bot model from the OpenRouter catalog in Settings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: README, full verification

**Files:**
- Modify: `README.md` (the "Configuration" section, after the paragraph starting "Every bot's model defaults to `auto`", ~line 477; and the `Run limits` row of the Settings reference table, ~line 522)

- [ ] **Step 1: Document the catalog and effort**

Insert after the "Every bot's model defaults to `auto` …" paragraph:

```markdown
The model pickers in the bot editor and in Settings list a catalog fetched from
[models.dev](https://models.dev) for OpenAI, Anthropic, OpenRouter and Ollama (for Ollama: the models
installed on your server first, then the models Ollama supports). Only models the agent loop can use
are listed: tool calling, text in and out, not deprecated, at least a 32k context. Each row shows the
price per million tokens, the context window and whether it supports reasoning, effort levels and
images. The catalog is cached in the database and refreshed in the background once it is a day old;
before the first fetch (or offline) the picker falls back to a short builtin list. Any model id can
still be typed by hand, whether or not the catalog knows it.

For models that declare reasoning effort levels, the bot editor offers an **Effort** setting (stored as
`model_settings.reasoning_effort`). It applies to OpenAI, xAI, OpenRouter and Anthropic models.
```

In the `Run limits` table row, change the last sentence to: ``` `model_settings` also accepts `reasoning_effort` (set from the Effort select for models that declare levels), `temperature`, `max_tokens`. ```

- [ ] **Step 2: Run everything**

Run from the worktree root: `make test && make lint`
Expected: backend and frontend suites pass, ruff, oxlint and the client-boundary check are clean.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: describe the model catalog, picker and effort setting

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Only configured providers list models (amendment, runs before Task 10)

**Files:**
- Modify: `backend/openbot/api/schemas.py` (`ModelsOut`)
- Modify: `backend/openbot/api/models.py`
- Modify: `backend/tests/test_models_api.py`
- Modify: `frontend/src/api/types.ts` (`ModelsOut`)
- Modify: `frontend/src/components/ModelPicker.tsx`
- Modify: `frontend/src/components/ModelPicker.test.tsx`, `frontend/src/pages/BotEditorPage.test.tsx`, `frontend/src/pages/SettingsPage.test.tsx` (fixtures gain `configured: true`)
- Modify: `README.md` (one sentence in the catalog paragraph, only if Task 10 has already run; otherwise Task 10 includes it)

**Interfaces:**
- Consumes: `provider_configured(settings, provider)` from `openbot.runtime.providers` (Ollama is configured when `ollama_base_url` is set; others when their API key is set).
- Produces: `ModelsOut.configured: bool` on the wire and in `types.ts`; the picker's "not configured" state.

- [ ] **Step 1: Write the failing backend test and adjust the existing ones**

In `backend/tests/test_models_api.py`, add:

```python
async def test_models_endpoint_lists_nothing_for_an_unconfigured_provider(client, services):
    services.model_catalog = ModelCatalog(services.session_factory, None)
    await _seed(services, "anthropic", normalize_catalog(SAMPLE)["anthropic"])
    body = (await client.get("/api/v1/models", params={"provider": "anthropic"})).json()
    assert body["configured"] is False and body["models"] == []
    services.settings.anthropic_api_key = "k"
    body = (await client.get("/api/v1/models", params={"provider": "anthropic"})).json()
    assert body["configured"] is True and body["models"][0]["id"] == "claude-opus-5-5"
```

The `client` fixture's settings have no keys, so the three existing tests that expect rows must configure their provider first. Add as the first line of each: `services.settings.openai_api_key = "k"` (builtin test; add `services` to its parameters), `services.settings.anthropic_api_key = "k"` (catalog test), `services.settings.openrouter_api_key = "k"` (empty-row test). Every existing assertion stays; add `and body["configured"] is True` to the builtin test's first assert line.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest -q tests/test_models_api.py`
Expected: the new test FAILS with `KeyError: 'configured'`.

- [ ] **Step 3: Implement**

`backend/openbot/api/schemas.py`, in `ModelsOut`, add after `provider: str`:

```python
    configured: bool
```

`backend/openbot/api/models.py`: import `provider_configured` alongside `PROVIDER_MODELS`, and replace the body after the 422 check with:

```python
    if not provider_configured(services.settings, provider):
        # No key (or no Ollama URL): nothing to list, and no reason to touch the catalog for it. Models of
        # this provider that OpenRouter serves are listed under openrouter already (anthropic/..., openai/...).
        return ModelsOut(provider=provider, configured=False, source="catalog", stale=False, fetched_at=None, models=[])
    catalog = services.model_catalog
    got = await catalog.get(provider) if catalog is not None else None
    if got is None:
        return ModelsOut(provider=provider, configured=True, source="builtin", stale=True, fetched_at=None,
                         models=[{"id": m, "name": m} for m in PROVIDER_MODELS[provider]])
    return ModelsOut(provider=provider, configured=True, source="catalog", stale=got.stale, fetched_at=got.fetched_at, models=got.models)
```

- [ ] **Step 4: Run backend tests and ruff**

Run: `cd backend && uv run pytest -q tests/test_models_api.py && uv run ruff check openbot/api/models.py openbot/api/schemas.py`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Write the failing picker test and update fixtures**

`frontend/src/api/types.ts`: add `configured: boolean;` to `ModelsOut` right after `provider`.

In every frontend test fixture that builds a `ModelsOut` (`ModelPicker.test.tsx` `catalog` and its builtin override, `BotEditorPage.test.tsx` `catalog`, `SettingsPage.test.tsx` `getModels` mock), add `configured: true`.

Append to `frontend/src/components/ModelPicker.test.tsx`:

```tsx
it("shows a not-configured notice and no rows when the provider has no key", async () => {
  vi.mocked(Api.getModels).mockResolvedValue({ ...catalog, configured: false, models: [] });
  await show({ initial: "claude-opus-5-5" });
  await focus();
  expect(options()).toEqual([]);
  expect(el.textContent).toContain("Anthropic is not configured. Add its API key in Settings.");
  expect(el.textContent).not.toContain("No matching models");
  expect(el.textContent).not.toContain("Not in the catalog");
  expect(el.querySelector("[data-chip=reasoning]")).toBeNull();
});
```

- [ ] **Step 6: Run to verify failure**

Run: `cd frontend && pnpm exec vitest run src/components/ModelPicker.test.tsx`
Expected: the new test FAILS (rows and chips render, notice absent).

- [ ] **Step 7: Implement the picker state**

In `frontend/src/components/ModelPicker.tsx`:

1. Add near the top:

```tsx
const PROVIDER_LABEL: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", openrouter: "OpenRouter", ollama: "Ollama" };
function notConfiguredText(provider: string): string {
  const name = PROVIDER_LABEL[provider] ?? provider;
  return provider === "ollama" ? `${name} is not configured. Set its base URL in Settings.` : `${name} is not configured. Add its API key in Settings.`;
}
```

2. After `const models = useQuery(...)` add `const unconfigured = models.data !== undefined && !models.data.configured;`.
3. Change the "Not in the catalog" note condition to `{!known && !models.isLoading && !unconfigured && (...)}`.
4. Inside the panel, render the notice instead of everything else when unconfigured: wrap the header, spinner, "No matching models." and groups in `{unconfigured ? (<div className="px-3 py-2 font-sans text-[13px] text-muted">{notConfiguredText(provider)}</div>) : (<> ...existing header, spinner, empty state and groups... </>)}`.

- [ ] **Step 8: Run all frontend checks**

Run: `cd frontend && pnpm exec vitest run src/components/ModelPicker.test.tsx && pnpm test && pnpm typecheck && pnpm lint`
Expected: all PASS, clean.

- [ ] **Step 9: Commit**

```bash
git add backend/openbot/api/schemas.py backend/openbot/api/models.py backend/tests/test_models_api.py frontend/src/api/types.ts frontend/src/components/ModelPicker.tsx frontend/src/components/ModelPicker.test.tsx frontend/src/pages/BotEditorPage.test.tsx frontend/src/pages/SettingsPage.test.tsx
git commit -m "feat(catalog): list models only for configured providers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Task 10's README paragraph gains this sentence after "...falls back to a short builtin list.": "Providers without a key (or Ollama without a base URL) list no models; their models served through OpenRouter still appear under OpenRouter."
