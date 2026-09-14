import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from openbot.config import Settings
from openbot.db.models import BotProfile
from openbot.runtime.providers import chat_model, default_provider, embeddings, provider_status


def s(**kw):
    return Settings(_env_file=None, **kw)


def test_chat_model_per_provider():
    st = s(openai_api_key="k1", anthropic_api_key="k2", openrouter_api_key="k3", xai_api_key="k4")
    m = chat_model(BotProfile(provider="openai", model="gpt-5.5", model_settings={"temperature": 0.2}), st)
    assert isinstance(m, ChatOpenAI) and m.temperature == 0.2
    m = chat_model(BotProfile(provider="anthropic", model="claude-sonnet-5", model_settings={}), st)
    assert isinstance(m, ChatAnthropic)
    m = chat_model(BotProfile(provider="openrouter", model="anthropic/claude-sonnet-5", model_settings={}), st)
    assert isinstance(m, ChatOpenAI) and "openrouter.ai" in str(m.openai_api_base)
    m = chat_model(BotProfile(provider="xai", model="grok-4.6", model_settings={}), st)
    assert isinstance(m, ChatOpenAI) and "x.ai" in str(m.openai_api_base)


def test_missing_key_raises():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        chat_model(BotProfile(provider="anthropic", model="x", model_settings={}), s())


def test_status_and_default():
    st = s(anthropic_api_key="k")
    status = {p["id"]: p for p in provider_status(st)}
    assert status["anthropic"]["configured"] and not status["openai"]["configured"]
    assert default_provider(st) == ("anthropic", "claude-sonnet-5")
    assert default_provider(s()) is None
    assert embeddings(s()) is None
    assert embeddings(s(openai_api_key="k")) is not None


async def test_providers_endpoint(client):
    r = await client.get("/api/v1/providers")
    assert r.status_code == 200 and {p["id"] for p in r.json()["providers"]} == {"openai", "anthropic", "openrouter", "xai"}
