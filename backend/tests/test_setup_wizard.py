"""Minimal .env, settings in the database, first-run setup (docs/superpowers/specs/2026-09-17-setup-wizard-design.md)."""
import asyncio
import json
import os

from sqlalchemy import select

from openbot.db.models import Actor, AppSetting
from openbot.runtime.app_settings import SETUP_COMPLETED_KEY, TUNABLES
from openbot.runtime.secrets import resolve_secret_key
from openbot.runtime.setup import setup_status

# --- secret key resolution --------------------------------------------------------------------------------

def test_secret_key_prefers_explicit_then_existing_files_then_creates_one(tmp_path, settings):
    settings.secret_key, settings.mcp_token_key = None, None
    settings.secret_key_file, settings.mcp_token_key_file = tmp_path / "secret.key", tmp_path / "mcp_token.key"
    settings.mcp_token_key_file.write_text("legacy-key")
    assert resolve_secret_key(settings) == "legacy-key"                       # an existing MCP key keeps old credentials readable
    settings.mcp_token_key_file.unlink()
    k = resolve_secret_key(settings)
    assert settings.secret_key_file.is_file() and resolve_secret_key(settings) == k
    settings.mcp_token_key = "explicit-legacy"
    assert resolve_secret_key(settings) == "explicit-legacy"
    settings.secret_key = "explicit-new"
    assert resolve_secret_key(settings) == "explicit-new"


# --- setup status ------------------------------------------------------------------------------------------

def test_status_is_incomplete_on_a_fresh_install_and_complete_once_the_minimum_is_met(settings):
    for k in ("openai_api_key", "anthropic_api_key", "openrouter_api_key", "xai_api_key", "ollama_base_url"):
        setattr(settings, k, None)
    settings.embedding_model = "openai:text-embedding-3-small"
    st = setup_status(settings)
    assert st["complete"] is False and st["chat"]["ok"] is False and st["embeddings"]["ok"] is False
    settings.openrouter_api_key = "k"
    st = setup_status(settings)
    assert st["chat"]["ok"] is True and st["chat"]["providers"] == ["openrouter"]
    assert st["embeddings"]["ok"] is False and "openai" in st["embeddings"]["reason"]   # model's provider has no key
    settings.embedding_model = ""
    assert setup_status(settings)["complete"] is True                                    # explicit "no semantic memory"
    settings.embedding_model, settings.openai_api_key = "openai:text-embedding-3-small", "ok"
    assert setup_status(settings)["complete"] is True
    settings.openrouter_api_key = settings.openai_api_key = None
    settings.ollama_base_url, settings.embedding_model = "http://localhost:11434", "ollama:nomic-embed-text"
    st = setup_status(settings)
    assert st["complete"] is True and st["chat"]["providers"] == ["ollama"]


async def test_setup_endpoint_and_completion_seeds_the_demo_team(client, services):
    settings = services.settings
    for k in ("openai_api_key", "anthropic_api_key", "openrouter_api_key", "xai_api_key", "ollama_base_url"):
        setattr(settings, k, None)
    settings.seed_demo_bots = True
    st = (await client.get("/api/v1/setup/status")).json()
    assert st["complete"] is False and set(st["missing"]) == {"chat", "embeddings"}
    async with services.session_factory() as s:
        assert (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars().all() == []
    r = await client.patch("/api/v1/settings", json={"openrouter_api_key": "or-key", "bot_model": "z-ai/glm-5.3-flash", "embedding_model": ""})
    assert r.status_code == 200, r.text
    assert (await client.get("/api/v1/setup/status")).json()["complete"] is True
    async with services.session_factory() as s:
        handles = sorted(a.handle for a in (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars())
    assert handles == ["chief_of_staff", "engineer", "qa", "reviewer"]                  # seeded on completion
    await client.patch("/api/v1/settings", json={"bot_model": "openai/gpt-5.5"})
    async with services.session_factory() as s:
        assert len((await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars().all()) == 4   # only once


async def test_setup_completed_marker_prevents_reseed(client, services):
    """After setup completes, a subsequent PATCH to an unrelated field does not re-seed.
    The _setup_completed marker gates seeding regardless of setup_status returning complete."""
    settings = services.settings
    for k in ("openai_api_key", "anthropic_api_key", "openrouter_api_key", "xai_api_key", "ollama_base_url"):
        setattr(settings, k, None)
    settings.seed_demo_bots = True
    r = await client.patch("/api/v1/settings", json={"openrouter_api_key": "or-key", "bot_model": "z-ai/glm-5.3-flash", "embedding_model": ""})
    assert r.status_code == 200, r.text
    async with services.session_factory() as s:
        assert await s.get(AppSetting, SETUP_COMPLETED_KEY) is not None
    # Now PATCH a completely unrelated field — setup is already complete so seeding is skipped.
    r = await client.patch("/api/v1/settings", json={"max_model_calls_per_run": 99})
    assert r.status_code == 200, r.text
    async with services.session_factory() as s:
        handles = sorted(a.handle for a in (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars())
    assert handles == ["chief_of_staff", "engineer", "qa", "reviewer"]  # only once


async def test_concurrent_patches_during_setup_do_not_500(client, services):
    """Two PATCHes that both make setup complete concurrently should not race to a 500."""
    settings = services.settings
    for k in ("openai_api_key", "anthropic_api_key", "openrouter_api_key", "xai_api_key", "ollama_base_url"):
        setattr(settings, k, None)
    settings.seed_demo_bots = True
    async with services.session_factory() as s:
        assert (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars().all() == []
    # Fire two PATCH requests concurrently; each provides a different API key plus embedding_model="" so both
    # independently make setup become complete.
    r1, r2 = await asyncio.gather(
        client.patch("/api/v1/settings", json={"openrouter_api_key": "or-key1", "bot_model": "z-ai/glm-5.3-flash", "embedding_model": ""}),
        client.patch("/api/v1/settings", json={"openai_api_key": "sk-key2", "bot_model": "z-ai/glm-5.3-flash", "embedding_model": ""}),
    )
    assert r1.status_code == 200, (r1.status_code, r1.text[:200])
    assert r2.status_code == 200, (r2.status_code, r2.text[:200])
    async with services.session_factory() as s:
        handles = sorted(a.handle for a in (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars())
    assert handles == ["chief_of_staff", "engineer", "qa", "reviewer"]  # seeded exactly once


# --- secret tunables ----------------------------------------------------------------------------------------

async def test_provider_keys_are_encrypted_at_rest_masked_in_the_api_and_resettable(client, services):
    settings = services.settings
    settings.openrouter_api_key = None
    rows = {r["key"]: r for r in (await client.get("/api/v1/settings")).json()}
    assert rows["openrouter_api_key"]["group"] == "Providers" and rows["openrouter_api_key"]["secret"] is True
    assert rows["openrouter_api_key"]["value"] is None and rows["openrouter_api_key"]["is_set"] is False
    r = await client.patch("/api/v1/settings", json={"openrouter_api_key": "sk-or-verysecret", "ollama_base_url": "http://localhost:11434"})
    assert r.status_code == 200, r.text
    row = {x["key"]: x for x in r.json()}["openrouter_api_key"]
    assert row["value"] == "••••••••" and row["is_set"] is True and row["overridden"] is True
    assert settings.openrouter_api_key == "sk-or-verysecret"                          # live for the next model call
    async with services.session_factory() as s:
        stored = (await s.get(AppSetting, "openrouter_api_key")).value
    assert "sk-or-verysecret" not in json.dumps(stored) and "enc" in stored
    # A masked value echoed back by the UI changes nothing; an empty value clears the key.
    await client.patch("/api/v1/settings", json={"openrouter_api_key": "••••••••"})
    assert settings.openrouter_api_key == "sk-or-verysecret"
    r = await client.delete("/api/v1/settings/openrouter_api_key")
    assert r.status_code == 200 and settings.openrouter_api_key is None
    # Stored secrets survive a restart, decrypted with the same key.
    await client.patch("/api/v1/settings", json={"anthropic_api_key": "sk-ant-1"})
    from openbot.runtime.app_settings import apply_stored_overrides
    settings.anthropic_api_key = None
    await apply_stored_overrides(services)
    assert settings.anthropic_api_key == "sk-ant-1"


def test_every_provider_and_embedding_setting_is_a_tunable():
    assert {"openai_api_key", "anthropic_api_key", "openrouter_api_key", "xai_api_key", "ollama_base_url", "ollama_model",
            "embedding_model", "embedding_dims"} <= set(TUNABLES)
    assert all(TUNABLES[k].secret for k in ("openai_api_key", "anthropic_api_key", "openrouter_api_key", "xai_api_key"))


# --- embeddings apply live ----------------------------------------------------------------------------------

async def test_changing_embeddings_reopens_the_memory_store(client, services):
    settings = services.settings
    settings.openai_api_key = None
    before = services.store
    checkpointer_before = services.checkpointer
    checkpointer_before = services.checkpointer
    r = await client.patch("/api/v1/settings", json={"embedding_model": "", "embedding_dims": 1536})
    assert r.status_code == 200, r.text
    assert services.store is not before                                               # reopened without a restart
    assert services.checkpointer is checkpointer_before                               # STO-2325: never reopened
    assert services.checkpointer is checkpointer_before                               # STO-2325: never reopened
    assert getattr(services.store, "index_config", None) in (None, {})                # no index: semantic memory off
    r = await client.patch("/api/v1/settings", json={"embedding_model": "ollama:nomic-embed-text", "embedding_dims": 768, "ollama_base_url": "http://localhost:11434"})
    assert r.status_code == 200, r.text
    assert services.store.index_config and services.store.index_config["dims"] == 768


async def test_embeddings_stored_only_in_the_database_survive_a_restart(settings):
    # STO-2323. Boot 1: a fresh install (no embedding configuration in the environment) completes the
    # wizard with Ollama embeddings, which are stored in the database only.
    from openbot.main import build_services, close_services
    from openbot.runtime.app_settings import update_settings
    fresh_env = settings.model_copy(deep=True)
    settings.embedding_model = ""
    fresh_env.embedding_model = ""
    first = await build_services(settings)
    try:
        assert getattr(first.store, "index_config", None) in (None, {})
        await update_settings(first, {"ollama_base_url": "http://localhost:11434",
                                      "embedding_model": "ollama:nomic-embed-text", "embedding_dims": 768})
        assert first.store.index_config["dims"] == 768                                 # applied live
    finally:
        await close_services(first)
    # Boot 2: same database, the environment still knows nothing about embeddings.
    second = await build_services(fresh_env)
    try:
        assert second.settings.embedding_model == "ollama:nomic-embed-text"            # override applied...
        assert second.store.index_config and second.store.index_config["dims"] == 768  # ...and the store opened with it
    finally:
        await close_services(second)


# --- .env.example ------------------------------------------------------------------------------------------

def test_env_example_holds_only_what_the_process_needs_to_start():
    from pathlib import Path
    text = Path(__file__).resolve().parents[2].joinpath(".env.example").read_text()
    names = {line.split("=", 1)[0].strip() for line in text.splitlines() if line.strip() and not line.startswith("#") and "=" in line}
    assert {"DATABASE_URL", "SECRET_KEY_FILE", "WORKSPACE_ROOT", "PUBLIC_URL"} <= names
    forbidden = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "XAI_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_MODEL",
                 "BOT_MODEL", "EMBEDDING_MODEL", "EMBEDDING_DIMS", "MAX_MODEL_CALLS_PER_RUN", "CONTEXT_TRIGGER_TOKENS"}
    assert not (forbidden & names), forbidden & names


def test_create_app_loads_the_dotenv_next_to_the_working_directory_not_the_package(tmp_path, settings, monkeypatch):
    # `make setup` copies .env.example into the directory the server is started from. Loading .env
    # relative to the package would pick up a developer's repo-root .env when the server runs elsewhere.
    (tmp_path / ".env").write_text("OPENBOT_DOTENV_PROBE=from-cwd\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENBOT_DOTENV_PROBE", raising=False)
    from openbot.main import create_app

    create_app(settings=settings)
    assert os.environ.get("OPENBOT_DOTENV_PROBE") == "from-cwd"