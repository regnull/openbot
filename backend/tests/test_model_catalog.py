import json
from pathlib import Path

import pytest

from openbot.runtime.model_catalog import CATALOG_PROVIDERS, normalize_catalog

SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "models_dev_sample.json").read_text())


def test_normalize_keeps_only_agent_capable_models_of_supported_providers():
    cat = normalize_catalog(SAMPLE)
    assert set(cat) == set(CATALOG_PROVIDERS) == {"openai", "anthropic", "openrouter", "ollama"}
    # deprecated, no tool calling, image output, no/invalid context, non-dict blocks, and the malformed entry are all gone
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
        "context": 200000, "output": 64000, "cost_input": 5.0, "cost_output": 25.0, "cost_cache_read": 0.5, "cost_cache_write": None, "cost_tiers": [], "release_date": "2026-03-01", "status": None,
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


def test_non_dict_block_inside_an_entry_is_skipped_not_fatal():
    raw = {"openai": {"models": {
        "bad": {"id": "bad", "tool_call": True, "modalities": ["text"], "limit": {"context": 100000}},
        "good": {"id": "good", "tool_call": True, "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 100000}},
    }}}
    assert [m["id"] for m in normalize_catalog(raw)["openai"]] == ["good"]


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


async def test_write_failure_returns_false_and_leaves_rows_untouched(services):
    await _seed(services, "openai", [{"id": "old"}], timedelta(hours=1))

    def failing_session_factory():
        session = services.session_factory()

        async def failing_commit() -> None:
            raise RuntimeError("disk full")

        session.commit = failing_commit
        return session

    client = httpx.AsyncClient(transport=httpx.MockTransport(_ok))
    cat = ModelCatalog(failing_session_factory, client)
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
