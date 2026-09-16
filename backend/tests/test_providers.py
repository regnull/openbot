import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from openbot.config import Settings
from openbot.db.models import BotProfile
from openbot.runtime.providers import (
    DEFAULT_BOT_MODEL,
    chat_model,
    configured_bot_model,
    default_provider,
    effective_bot_profile,
    embeddings,
    provider_status,
)


def s(**kw):
    return Settings(_env_file=None, **kw)


def test_chat_model_per_provider():
    m = chat_model(
        BotProfile(provider="openai", model="gpt-4.1-mini", model_settings={"temperature": 0.2}),
        s(openai_api_key="k1"),
    )
    assert isinstance(m, ChatOpenAI) and m.temperature == 0.2
    m = chat_model(
        BotProfile(provider="anthropic", model="claude-sonnet-5", model_settings={}),
        s(anthropic_api_key="k2"),
    )
    assert isinstance(m, ChatAnthropic)
    m = chat_model(
        BotProfile(provider="openrouter", model="anthropic/claude-sonnet-5", model_settings={}),
        s(openrouter_api_key="k3", bot_model="anthropic/claude-sonnet-5"),
    )
    assert isinstance(m, ChatOpenAI) and "openrouter.ai" in str(m.openai_api_base)
    m = chat_model(
        BotProfile(provider="xai", model="grok-4.6", model_settings={}),
        s(xai_api_key="k4"),
    )
    assert isinstance(m, ChatOpenAI) and "x.ai" in str(m.openai_api_base)


def test_missing_key_raises():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        chat_model(BotProfile(provider="anthropic", model="x", model_settings={}), s())


def test_status_and_default():
    st = s(anthropic_api_key="k")
    status = {p["id"]: p for p in provider_status(st)}
    assert status["anthropic"]["configured"] and not status["openai"]["configured"]
    assert status["openrouter"]["default_model"] == DEFAULT_BOT_MODEL
    assert default_provider(st) == ("anthropic", "claude-sonnet-5")
    assert default_provider(s(openrouter_api_key="k", anthropic_api_key="k")) == ("openrouter", DEFAULT_BOT_MODEL)
    assert default_provider(s(openrouter_api_key="k", bot_model="anthropic/claude-3.5-haiku")) == (
        "openrouter",
        "anthropic/claude-3.5-haiku",
    )
    assert default_provider(s()) is None
    assert embeddings(s()) is None
    assert embeddings(s(openai_api_key="k")) is not None


async def test_providers_endpoint(client):
    r = await client.get("/api/v1/providers")
    assert r.status_code == 200 and {p["id"] for p in r.json()["providers"]} == {"auto", "openai", "anthropic", "openrouter", "xai", "ollama"}


def test_status_includes_auto_provider():
    status = {p["id"]: p for p in provider_status(s(anthropic_api_key="k"))}
    assert status["auto"]["configured"] is True
    assert status["auto"]["default_model"] == "anthropic/claude-sonnet-5"
    assert status["auto"]["models"] == []
    assert provider_status(s())[0]["id"] == "auto"
    assert provider_status(s())[0]["configured"] is False
    assert provider_status(s())[0]["default_model"] == ""


def test_configured_bot_model_default_and_env_override(monkeypatch):
    monkeypatch.delenv("BOT_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    assert configured_bot_model(s()) == DEFAULT_BOT_MODEL

    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")
    assert Settings(_env_file=None).openrouter_model == "google/gemini-2.0-flash-001"
    assert configured_bot_model(Settings(_env_file=None)) == "google/gemini-2.0-flash-001"

    monkeypatch.setenv("BOT_MODEL", "anthropic/claude-3.5-haiku")
    assert Settings(_env_file=None).bot_model == "anthropic/claude-3.5-haiku"
    assert configured_bot_model(Settings(_env_file=None)) == "anthropic/claude-3.5-haiku"


def test_openrouter_bots_use_configured_model_for_llm_calls():
    st = s(openrouter_api_key="k", bot_model="google/gemini-2.0-flash-001")
    m = chat_model(BotProfile(provider="openrouter", model="stored/old-model", model_settings={}), st)
    assert m.model_name == "google/gemini-2.0-flash-001"
    assert "openrouter.ai" in str(m.openai_api_base)


def test_env_model_applies_to_all_bot_llm_calls_through_openrouter():
    st = s(openai_api_key="k1", openrouter_api_key="k2", bot_model="google/gemini-2.0-flash-001")
    m = chat_model(BotProfile(provider="openai", model="gpt-4.1-mini", model_settings={}), st)
    assert m.model_name == "google/gemini-2.0-flash-001"
    assert "openrouter.ai" in str(m.openai_api_base)


def test_existing_provider_model_is_preserved_without_openrouter_config():
    st = s(openai_api_key="k", bot_model="google/gemini-2.0-flash-001")
    m = chat_model(BotProfile(provider="openai", model="gpt-4.1-mini", model_settings={}), st)
    assert m.model_name == "gpt-4.1-mini"
    assert not m.openai_api_base


def test_auto_provider_resolves_to_whatever_is_configured():
    st = s(anthropic_api_key="k")
    assert effective_bot_profile(BotProfile(provider="auto", model=""), st) == ("anthropic", "claude-sonnet-5")
    m = chat_model(BotProfile(provider="auto", model="", model_settings={}), st)
    assert isinstance(m, ChatAnthropic)


def test_auto_provider_follows_openrouter_env_override():
    st = s(openrouter_api_key="k", bot_model="google/gemini-2.0-flash-001")
    assert effective_bot_profile(BotProfile(provider="auto", model=""), st) == ("openrouter", "google/gemini-2.0-flash-001")


def test_auto_provider_without_any_key_raises():
    with pytest.raises(ValueError, match="no provider is configured"):
        chat_model(BotProfile(provider="auto", model="", model_settings={}), s())
