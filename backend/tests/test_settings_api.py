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
    assert {r["group"] for r in rows} == {"Providers", "Embeddings", "Run limits", "Context", "Memory", "Model routing", "Model retries", "Telegram"}


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


async def test_telegram_bot_token_is_editable_via_settings(client, services):
    """Telegram bot token can be set, is masked in the response, and applies live."""
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg"
    r = await client.patch("/api/v1/settings", json={"telegram_bot_token": token})
    assert r.status_code == 200, r.text
    by_key = {x["key"]: x for x in r.json()}
    t = by_key["telegram_bot_token"]
    assert t["group"] == "Telegram"
    assert t["type"] == "secret"
    assert t["secret"] is True
    assert t["overridden"] is True
    assert t["is_set"] is True
    # The plaintext token must never appear in the API response.
    assert t["value"] != token
    assert t["value"] == "••••••••"
    # Live apply: the settings object now holds the real token.
    assert services.settings.telegram_bot_token == token
    # Reset restores the env default (None when not set via env).
    r2 = await client.delete("/api/v1/settings/telegram_bot_token")
    assert r2.status_code == 200
    assert services.settings.telegram_bot_token is None


async def test_telegram_bot_token_rejects_invalid_format(client, services):
    """Obviously invalid tokens are rejected."""
    for bad in ("no-colon", "123:short", "123:$$invalid$$chars$$"):
        r = await client.patch("/api/v1/settings", json={"telegram_bot_token": bad})
        assert r.status_code == 422, (bad, r.text)
    # The original value is unchanged.
    assert services.settings.telegram_bot_token is None


async def test_telegram_webhook_settings_are_editable(client, services):
    """Webhook URL and secret can be set and reset."""
    url = "https://example.com/api/v1/channels/telegram/webhook"
    secret = "my-shared-secret-123"
    r = await client.patch("/api/v1/settings", json={
        "telegram_webhook_url": url,
        "telegram_webhook_secret": secret,
    })
    assert r.status_code == 200, r.text
    by_key = {x["key"]: x for x in r.json()}
    assert by_key["telegram_webhook_url"]["value"] == url
    assert by_key["telegram_webhook_url"]["secret"] is False
    assert by_key["telegram_webhook_secret"]["value"] == "••••••••"
    assert by_key["telegram_webhook_secret"]["secret"] is True
    assert services.settings.telegram_webhook_url == url
    assert services.settings.telegram_webhook_secret == secret


async def test_telegram_token_masked_update_is_noop(client, services):
    """Sending the masked value back (as the UI would when other fields change) is a no-op."""
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg"
    await client.patch("/api/v1/settings", json={"telegram_bot_token": token})
    assert services.settings.telegram_bot_token == token
    # Simulate the UI sending the masked value when saving other fields in the group.
    from openbot.runtime.app_settings import MASK
    r = await client.patch("/api/v1/settings", json={"telegram_bot_token": MASK})
    assert r.status_code == 200
    # The real token is preserved.
    assert services.settings.telegram_bot_token == token
