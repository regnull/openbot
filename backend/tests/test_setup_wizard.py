"""Minimal .env, settings in the database, first-run setup (docs/superpowers/specs/2026-09-17-setup-wizard-design.md)."""
import json

from sqlalchemy import select

from openbot.db.models import Actor, AppSetting
from openbot.runtime.app_settings import TUNABLES
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
    r = await client.patch("/api/v1/settings", json={"embedding_model": "", "embedding_dims": 1536})
    assert r.status_code == 200, r.text
    assert services.store is not before                                               # reopened without a restart
    assert getattr(services.store, "index_config", None) in (None, {})                # no index: semantic memory off
    r = await client.patch("/api/v1/settings", json={"embedding_model": "ollama:nomic-embed-text", "embedding_dims": 768, "ollama_base_url": "http://localhost:11434"})
    assert r.status_code == 200, r.text
    assert services.store.index_config and services.store.index_config["dims"] == 768


# --- .env.example ------------------------------------------------------------------------------------------

def test_env_example_holds_only_what_the_process_needs_to_start():
    from pathlib import Path
    text = Path(__file__).resolve().parents[2].joinpath(".env.example").read_text()
    names = {line.split("=", 1)[0].strip() for line in text.splitlines() if line.strip() and not line.startswith("#") and "=" in line}
    assert {"DATABASE_URL", "SECRET_KEY_FILE", "WORKSPACE_ROOT", "PUBLIC_URL"} <= names
    forbidden = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "XAI_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_MODEL",
                 "BOT_MODEL", "EMBEDDING_MODEL", "EMBEDDING_DIMS", "MAX_MODEL_CALLS_PER_RUN", "CONTEXT_TRIGGER_TOKENS"}
    assert not (forbidden & names), forbidden & names
