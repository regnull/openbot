"""Local Ollama models: configured by OLLAMA_BASE_URL (no API key), never rerouted through
OpenRouter, and the providers endpoint lists the models the Ollama server actually has."""
import httpx
import pytest
from langchain_ollama import ChatOllama, OllamaEmbeddings

from openbot.config import Settings
from openbot.db.models import BotProfile
from openbot.runtime.providers import (
    chat_model,
    default_provider,
    effective_bot_profile,
    embeddings,
    list_ollama_models,
    provider_status,
)


def s(**kw):
    return Settings(_env_file=None, **kw)


def test_ollama_chat_model_uses_base_url_and_model_settings():
    m = chat_model(BotProfile(provider="ollama", model="qwen3:8b", model_settings={"temperature": 0.1, "max_tokens": 512}),
                   s(ollama_base_url="http://ollama.local:11434"))
    assert isinstance(m, ChatOllama)
    assert m.model == "qwen3:8b" and m.base_url == "http://ollama.local:11434"
    assert m.temperature == 0.1 and m.num_predict == 512


def test_ollama_not_configured_raises_with_env_hint():
    with pytest.raises(ValueError, match="OLLAMA_BASE_URL"):
        chat_model(BotProfile(provider="ollama", model="llama3.1", model_settings={}), s())


def test_ollama_bot_is_not_rerouted_through_openrouter():
    st = s(openrouter_api_key="k", bot_model="google/gemini-2.0-flash-001", ollama_base_url="http://localhost:11434")
    bot = BotProfile(provider="ollama", model="llama3.1", model_settings={})
    assert effective_bot_profile(bot, st) == ("ollama", "llama3.1")
    assert isinstance(chat_model(bot, st), ChatOllama)


def test_empty_ollama_base_url_env_means_not_configured(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "")
    st = Settings(_env_file=None)
    assert st.ollama_base_url is None
    assert not {p["id"]: p for p in provider_status(st)}["ollama"]["configured"]


def test_provider_status_includes_ollama_and_prefers_installed_models():
    st = s(ollama_base_url="http://localhost:11434", ollama_model="llama3.1")
    status = {p["id"]: p for p in provider_status(st)}
    assert status["ollama"]["configured"] and status["ollama"]["default_model"] == "llama3.1"
    assert status["ollama"]["models"][0] == "llama3.1"
    status = {p["id"]: p for p in provider_status(st, ollama_models=["gemma3:4b", "llama3.1:latest"])}
    assert status["ollama"]["models"] == ["gemma3:4b", "llama3.1:latest"]
    # the configured default is installed (as a tagged name), so it stays the default
    assert status["ollama"]["default_model"] == "llama3.1"
    # when it is not installed, the first installed model becomes the default so new bots work
    status = {p["id"]: p for p in provider_status(st, ollama_models=["gemma3:4b", "qwen3.5:latest"])}
    assert status["ollama"]["default_model"] == "gemma3:4b"


def test_ollama_is_a_default_provider_when_nothing_else_is_configured():
    assert default_provider(s(ollama_base_url="http://localhost:11434", ollama_model="qwen3")) == ("ollama", "qwen3")
    # a cloud key still wins: local models are an explicit opt-in per bot
    assert default_provider(s(ollama_base_url="http://localhost:11434", anthropic_api_key="k"))[0] == "anthropic"


def test_ollama_embeddings():
    assert embeddings(s(embedding_model="ollama:nomic-embed-text")) is None
    e = embeddings(s(embedding_model="ollama:nomic-embed-text", ollama_base_url="http://localhost:11434"))
    assert isinstance(e, OllamaEmbeddings) and e.model == "nomic-embed-text"


async def test_list_ollama_models_parses_tags_and_tolerates_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "llama3.1:latest"}, {"name": "gemma3:4b"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await list_ollama_models(s(ollama_base_url="http://localhost:11434/"), client) == ["gemma3:4b", "llama3.1:latest"]

    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(failing)) as client:
        assert await list_ollama_models(s(ollama_base_url="http://localhost:11434"), client) is None
    assert await list_ollama_models(s(), None) is None


async def test_providers_endpoint_includes_ollama(client):
    r = await client.get("/api/v1/providers")
    ids = {p["id"] for p in r.json()["providers"]}
    assert "ollama" in ids


async def test_bots_api_accepts_ollama_provider(client):
    r = await client.post("/api/v1/bots", json={"handle": "local", "name": "Local", "description": "d", "instructions": "i",
                                               "provider": "ollama", "model": "llama3.1"})
    assert r.status_code == 201, r.text
    assert r.json()["provider"] == "ollama"
