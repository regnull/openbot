"""Runtime settings: tunables the operator edits in the UI, layered over the environment."""
from sqlalchemy import inspect

from openbot.db.session import make_engine, run_migrations
from openbot.runtime.app_settings import TUNABLES, load_overrides


async def test_settings_listing_shows_every_tunable_with_its_default(client, services):
    rows = (await client.get("/api/v1/settings")).json()
    by_key = {r["key"]: r for r in rows}
    assert set(by_key) == set(TUNABLES)
    r = by_key["max_model_calls_per_run"]
    assert r["value"] == r["default"] == services.settings.max_model_calls_per_run and r["overridden"] is False
    assert r["group"] == "Run limits" and r["type"] == "int" and r["label"] and r["description"]
    assert {r["group"] for r in rows} == {"Providers", "Embeddings", "Run limits", "Context", "Memory", "Model routing", "Model retries"}


async def test_patch_applies_live_persists_and_reset_restores_the_environment_value(client, services):
    env_value = services.settings.max_model_calls_per_run
    r = await client.patch("/api/v1/settings", json={"max_model_calls_per_run": 7, "openrouter_provider_order": "z-ai, fireworks",
                                                    "prompt_caching": False})
    assert r.status_code == 200, r.text
    by_key = {x["key"]: x for x in r.json()}
    assert by_key["max_model_calls_per_run"]["value"] == 7 and by_key["max_model_calls_per_run"]["overridden"] is True
    assert by_key["openrouter_provider_order"]["value"] == ["z-ai", "fireworks"]      # CSV accepted, like the env
    assert by_key["prompt_caching"]["value"] is False
    # Live: the runner reads services.settings at call time, so the next run sees it without a restart.
    assert services.settings.max_model_calls_per_run == 7 and services.settings.prompt_caching is False
    # Persisted: a fresh process would load the same overrides.
    assert (await load_overrides(services.session_factory))["max_model_calls_per_run"] == 7
    r = await client.delete("/api/v1/settings/max_model_calls_per_run")
    assert r.status_code == 200
    assert services.settings.max_model_calls_per_run == env_value
    assert "max_model_calls_per_run" not in await load_overrides(services.session_factory)
    assert {x["key"]: x["overridden"] for x in r.json()}["max_model_calls_per_run"] is False


async def test_patch_rejects_unknown_keys_bad_types_and_out_of_range_values(client, services):
    before = services.settings.max_model_calls_per_run
    for body in ({"database_url": "sqlite://x"}, {"nope": 1}, {"max_model_calls_per_run": "many"},
                 {"max_model_calls_per_run": 0}, {"history_token_budget": -5}, {"max_model_calls_per_run": 5, "max_bot_hops": "x"}):
        r = await client.patch("/api/v1/settings", json=body)
        assert r.status_code == 422, (body, r.text)
    assert services.settings.max_model_calls_per_run == before                        # nothing applied on a bad batch
    assert (await client.delete("/api/v1/settings/database_url")).status_code == 422


async def test_reflection_delay_reaches_the_running_reflector(client, services):
    await client.patch("/api/v1/settings", json={"memory_reflection_delay": 1.5})
    assert services.reflector.delay == 1.5


async def test_stored_overrides_are_applied_at_startup(settings, tmp_path):
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from openbot.main import create_app
    from tests.conftest import build_test_services

    fresh = settings.model_copy()          # what a new process would load from the environment
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.patch("/api/v1/settings", json={"max_bot_hops": 3})).status_code == 200
    # Same database, new process: the environment default is 20, the stored override wins.
    services2 = await build_test_services(fresh)
    assert services2.settings.max_bot_hops == 20
    app2 = create_app(fresh, services=services2)
    async with LifespanManager(app2):
        assert services2.settings.max_bot_hops == 3


async def test_migration_adds_app_settings_table(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    await engine.dispose()
    assert "app_settings" in tables


def test_model_call_default_gives_a_real_task_room():
    from openbot.config import Settings
    assert Settings(_env_file=None).max_model_calls_per_run == 60
