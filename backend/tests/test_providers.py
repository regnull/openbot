import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from openbot.config import Settings
from openbot.db.models import BotProfile
from openbot.runtime.providers import (
    DEFAULT_BOT_MODEL,
    builtin_tools,
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


def test_reasoning_effort_passes_through_to_openai_compatible_models():
    """GLM spent 7k reasoning tokens deciding to run `node --version`. Operators can turn the effort
    down per bot from model_settings; the OpenAI-compatible endpoints (OpenRouter included) accept it."""
    m = chat_model(BotProfile(provider="openrouter", model="z-ai/glm-5.3-flash", model_settings={"reasoning_effort": "low"}),
                   s(openrouter_api_key="k", direct_anthropic=False))
    assert isinstance(m, ChatOpenAI) and m.reasoning_effort == "low"
    m = chat_model(BotProfile(provider="openrouter", model="z-ai/glm-5.3-flash", model_settings={}), s(openrouter_api_key="k"))
    assert m.reasoning_effort is None


def test_openrouter_provider_order_prefers_the_upstream_but_keeps_fallbacks():
    """OpenRouter serves this model from 26 upstreams, each with its own prompt cache; a request that
    lands elsewhere is a full cache miss. Pinning keeps the cache warm."""
    st = s(openrouter_api_key="k", openrouter_provider_order="z-ai,fireworks")
    assert st.openrouter_provider_order == ["z-ai", "fireworks"]
    m = chat_model(BotProfile(provider="openrouter", model="z-ai/glm-5.3-flash"), st)
    # Preference, not a hard pin: with fallbacks off, a request the preferred upstream cannot serve (memory
    # extraction sends tool_choice=required, which Z.AI rejects) got "No endpoints found" instead of a
    # cold-cache answer from another upstream. Preferred-first still keeps the cache warm in the common case.
    assert m.extra_body == {"provider": {"order": ["z-ai", "fireworks"], "allow_fallbacks": True}}
    m = chat_model(BotProfile(provider="openrouter", model="z-ai/glm-5.3-flash"), s(openrouter_api_key="k"))
    assert not m.extra_body
    m = chat_model(BotProfile(provider="openai", model="gpt-4.1-mini"), s(openai_api_key="k", openrouter_provider_order="z-ai"))
    assert not m.extra_body                                        # pinning is an OpenRouter concept only


def test_openrouter_embeddings_use_its_openai_compatible_endpoint():
    """OpenRouter serves embeddings at /api/v1/embeddings with the OpenAI wire format, so one OpenRouter key
    can power both chat and memory search. The model name is OpenRouter's (openai/text-embedding-3-small),
    which tiktoken does not know, so the client must not try to tokenize inputs locally."""
    from langchain_openai import OpenAIEmbeddings
    e = embeddings(s(openrouter_api_key="k", embedding_model="openrouter:openai/text-embedding-3-small"))
    assert isinstance(e, OpenAIEmbeddings) and e.model == "openai/text-embedding-3-small"
    assert e.openai_api_base == "https://openrouter.ai/api/v1" and e.check_embedding_ctx_length is False
    assert e.default_headers == {"X-Title": "OpenBot"}
    assert embeddings(s(embedding_model="openai:text-embedding-3-small", openai_api_key="k")).default_headers is None
    assert embeddings(s(embedding_model="openrouter:openai/text-embedding-3-small")) is None      # no key: off


def test_web_search_does_not_bind_tools_on_the_model():
    """Provider-hosted search is passed to create_agent as a built-in tool (see builtin_tools), never bound on
    the model: the agent rebinds its own tools onto the model and would drop a pre-bound one, and the same
    model factory serves memory extraction and thread renaming, which must not search the web."""
    openai = chat_model(BotProfile(provider="openai", model="gpt-5.5", model_settings={"web_search": True}), s(openai_api_key="k"))
    assert isinstance(openai, ChatOpenAI) and openai.use_responses_api is True
    anthropic = chat_model(BotProfile(provider="anthropic", model="claude-sonnet-5", model_settings={"web_search": True}), s(anthropic_api_key="k"))
    assert isinstance(anthropic, ChatAnthropic)
    router = chat_model(BotProfile(provider="openrouter", model="openai/gpt-5.5", model_settings={"web_search": True}), s(openrouter_api_key="k", direct_anthropic=False))
    assert router.extra_body["plugins"] == [{"id": "web"}]


def test_builtin_tools_per_provider():
    on = {"web_search": True}
    assert builtin_tools(BotProfile(provider="openai", model="gpt-5.5", model_settings=on), s(openai_api_key="k")) == [{"type": "web_search_preview"}]
    assert builtin_tools(BotProfile(provider="anthropic", model="claude-sonnet-5", model_settings=on), s(anthropic_api_key="k")) == [
        {"type": "web_search_20250305", "name": "web_search"}]
    # OpenRouter searches through its request-level plugin, xAI and Ollama have no hosted search.
    assert builtin_tools(BotProfile(provider="openrouter", model="openai/gpt-5.5", model_settings=on), s(openrouter_api_key="k", direct_anthropic=False)) == []
    assert builtin_tools(BotProfile(provider="xai", model="grok-4.6", model_settings=on), s(xai_api_key="k")) == []
    assert builtin_tools(BotProfile(provider="ollama", model="llama3.1", model_settings=on), s(ollama_base_url="http://localhost:11434")) == []


def test_builtin_tools_off_by_default_and_follow_effective_provider():
    assert builtin_tools(BotProfile(provider="anthropic", model="claude-sonnet-5", model_settings={}), s(anthropic_api_key="k")) == []
    # auto resolves to the configured provider; an OpenRouter anthropic/ model sent direct gets Anthropic's tool.
    auto = BotProfile(provider="auto", model="", model_settings={"web_search": True})
    assert builtin_tools(auto, s(openai_api_key="k")) == [{"type": "web_search_preview"}]
    assert builtin_tools(auto, s(openrouter_api_key="k", anthropic_api_key="k", bot_model="anthropic/claude-sonnet-5")) == [
        {"type": "web_search_20250305", "name": "web_search"}]
    # No provider configured at all: nothing to add rather than an error (the run itself reports the missing key).
    assert builtin_tools(auto, s()) == []


def test_web_search_is_disabled_by_default():
    model = chat_model(BotProfile(provider="openai", model="gpt-5.5", model_settings={}), s(openai_api_key="k"))
    assert not model.model_kwargs


def test_web_search_opt_in_survives_auto_provider_model_resolution():
    """The persisted bot setting is passed through after auto selects provider and model."""
    bot = BotProfile(provider="auto", model="", model_settings={"web_search": True})
    model = chat_model(bot, s(openrouter_api_key="k", bot_model="openai/gpt-5.5"))
    assert model.model_name == "openai/gpt-5.5"
    assert model.extra_body["plugins"] == [{"id": "web"}]


@pytest.mark.parametrize("provider, model, settings", [
    ("xai", "grok-4.6", {"xai_api_key": "k"}),
    ("ollama", "llama3.1", {"ollama_base_url": "http://localhost:11434"}),
])
def test_web_search_opt_in_does_not_change_unsupported_providers(provider, model, settings):
    """Providers without a native search mechanism retain their normal model setup."""
    search = chat_model(BotProfile(provider=provider, model=model, model_settings={"web_search": True}), s(**settings))
    normal = chat_model(BotProfile(provider=provider, model=model, model_settings={}), s(**settings))
    if provider == "ollama":
        assert search.model == normal.model == model
    else:
        assert search.model_name == normal.model_name == model
        assert not search.model_kwargs


@pytest.mark.parametrize("provider, model, settings", [
    ("openai", "gpt-5.5", {"openai_api_key": "k"}),
    ("anthropic", "claude-sonnet-5", {"anthropic_api_key": "k"}),
    ("openrouter", "openai/gpt-5.5", {"openrouter_api_key": "k"}),
])
def test_web_search_is_disabled_by_default_for_every_supported_provider(provider, model, settings):
    model_instance = chat_model(BotProfile(provider=provider, model=model, model_settings={}), s(**settings))
    assert not model_instance.model_kwargs
    if provider == "openrouter":
        assert not (model_instance.extra_body or {}).get("plugins")

