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


async def test_models_endpoint_falls_back_to_the_builtin_list_before_the_first_fetch(client, services):
    services.settings.openai_api_key = "k"
    r = await client.get("/api/v1/models", params={"provider": "openai"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "openai" and body["source"] == "builtin" and body["stale"] is True and body["fetched_at"] is None and body["configured"] is True
    assert [m["id"] for m in body["models"]] == PROVIDER_MODELS["openai"]
    first = body["models"][0]
    assert first["name"] == first["id"] and first["effort_levels"] == [] and first["cost_input"] is None and first["context"] is None


async def test_models_endpoint_serves_catalog_rows(client, services):
    services.settings.anthropic_api_key = "k"
    services.model_catalog = ModelCatalog(services.session_factory, None)
    await _seed(services, "anthropic", normalize_catalog(SAMPLE)["anthropic"])
    body = (await client.get("/api/v1/models", params={"provider": "anthropic"})).json()
    assert body["source"] == "catalog" and body["stale"] is False and body["fetched_at"]
    assert body["models"][0]["id"] == "claude-opus-5-5"
    assert body["models"][0]["effort_levels"] == ["low", "medium", "high", "xhigh", "max"]
    assert body["models"][0]["cost_output"] == 25.0


async def test_models_endpoint_serves_an_empty_catalog_row_as_empty_not_builtin(client, services):
    services.settings.openrouter_api_key = "k"
    services.model_catalog = ModelCatalog(services.session_factory, None)
    await _seed(services, "openrouter", [])
    body = (await client.get("/api/v1/models", params={"provider": "openrouter"})).json()
    assert body["source"] == "catalog" and body["models"] == []


async def test_models_endpoint_rejects_providers_without_a_catalog(client):
    for p in ("auto", "xai", "nope"):
        assert (await client.get("/api/v1/models", params={"provider": p})).status_code == 422, p
    assert (await client.get("/api/v1/models")).status_code == 422


async def test_models_endpoint_lists_nothing_for_an_unconfigured_provider(client, services):
    services.model_catalog = ModelCatalog(services.session_factory, None)
    await _seed(services, "anthropic", normalize_catalog(SAMPLE)["anthropic"])
    body = (await client.get("/api/v1/models", params={"provider": "anthropic"})).json()
    assert body["configured"] is False and body["models"] == []
    services.settings.anthropic_api_key = "k"
    body = (await client.get("/api/v1/models", params={"provider": "anthropic"})).json()
    assert body["configured"] is True and body["models"][0]["id"] == "claude-opus-5-5"
