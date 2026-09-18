from __future__ import annotations

import logging

import httpx
from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from openbot.config import Settings
from openbot.db.models import BotProfile

log = logging.getLogger(__name__)

AUTO_PROVIDER = "auto"
DEFAULT_BOT_PROVIDER = "openrouter"
DEFAULT_BOT_MODEL = "openai/gpt-4o-mini"
OLLAMA = "ollama"

PROVIDER_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5-mini"],
    "anthropic": ["claude-sonnet-5", "claude-opus-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"],
    "openrouter": [
        DEFAULT_BOT_MODEL,
        "anthropic/claude-sonnet-5",
        "openai/gpt-5.5",
        "x-ai/grok-4.6",
        "openai/gpt-oss-120b",
    ],
    "xai": ["grok-4.6", "grok-4.5"],
    # Fallback suggestions only; when the Ollama server is reachable the installed models replace these.
    OLLAMA: ["llama3.1", "qwen3", "gpt-oss:20b", "gemma3", "deepseek-r1"],
}
DEFAULT_MODEL = {p: models[0] for p, models in PROVIDER_MODELS.items()}
PROVIDER_ORDER = ["openai", "anthropic", "openrouter", "xai", OLLAMA]
# Order in which providers are listed for the UI/API; "auto" is always first since it is the default.
STATUS_PROVIDER_ORDER = [AUTO_PROVIDER, *PROVIDER_ORDER]
_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "xai": "XAI_API_KEY",
    OLLAMA: "OLLAMA_BASE_URL",
}
_BASE_URL = {"openrouter": "https://openrouter.ai/api/v1", "xai": "https://api.x.ai/v1"}
OLLAMA_TAGS_TIMEOUT = 2.0


def api_key_for(settings: Settings, provider: str) -> str | None:
    return getattr(settings, f"{provider}_api_key", None)


def provider_configured(settings: Settings, provider: str) -> bool:
    """Ollama is a local server with no API key: it is configured when OLLAMA_BASE_URL is set."""
    if provider == OLLAMA:
        return bool(settings.ollama_base_url)
    return bool(api_key_for(settings, provider))


def configured_bot_model(settings: Settings) -> str:
    return settings.bot_model or settings.openrouter_model or DEFAULT_BOT_MODEL


def effective_bot_profile(bot: BotProfile, settings: Settings) -> tuple[str, str]:
    """Return the provider/model to use for a bot LLM call.

    A bot with provider "auto" (the default for new bots) always resolves to whichever provider is
    configured (see `default_provider`), so it keeps working as keys are added, removed, or changed
    without ever needing to be edited.

    For bots with an explicit cloud provider, a configured OpenRouter key makes OpenRouter the
    runtime provider for every bot, so the team can be moved to another OpenRouter model from `.env`
    without editing persisted bot rows one by one. Installations without OpenRouter configured keep
    using each bot's stored provider/model, even if BOT_MODEL/OPENROUTER_MODEL is set.

    A bot on a local Ollama model is an explicit choice to keep that bot off the cloud, so it is
    never rerouted through OpenRouter.
    """
    if bot.provider == AUTO_PROVIDER:
        dp = default_provider(settings)
        if dp is None:
            raise ValueError("no provider is configured: set an API key for at least one provider")
        return prefer_direct_anthropic(dp[0], dp[1], settings)
    if bot.provider == OLLAMA:
        return bot.provider, bot.model
    if api_key_for(settings, DEFAULT_BOT_PROVIDER):
        return prefer_direct_anthropic(DEFAULT_BOT_PROVIDER, configured_bot_model(settings), settings)
    return bot.provider, bot.model


def prefer_direct_anthropic(provider: str, model: str, settings: Settings) -> tuple[str, str]:
    """Send an OpenRouter `anthropic/...` model straight to Anthropic when a key is configured.

    Prompt caching is what keeps long agent runs affordable, and it only fully works (tool results
    included) on the direct Anthropic API; through OpenRouter's OpenAI-compatible endpoint only the
    system prompt and human turns can carry cache breakpoints. Same list price, no OpenRouter fee.
    Disable with DIRECT_ANTHROPIC=false."""
    if (provider == "openrouter" and model.startswith("anthropic/") and settings.direct_anthropic
            and api_key_for(settings, "anthropic")):
        return "anthropic", openrouter_to_anthropic_model(model)
    return provider, model


def openrouter_to_anthropic_model(model: str) -> str:
    """`anthropic/claude-opus-4.6` -> `claude-opus-4-6` (Anthropic ids use dashes in version numbers)."""
    name = model.split("/", 1)[1]
    return name.replace(".", "-")


def provider_chat_model(
    provider: str,
    model: str,
    settings: Settings,
    model_settings: dict | None = None,
) -> BaseChatModel:
    """Build a chat model for an explicit provider/model without bot-level env overrides."""
    if not provider_configured(settings, provider):
        raise ValueError(f"provider {provider} is not configured: set {_KEY_ENV[provider]}")
    ms = dict(model_settings or {})
    kwargs: dict = {}
    if "temperature" in ms:
        kwargs["temperature"] = ms["temperature"]
    if "max_tokens" in ms:
        kwargs["max_tokens"] = ms["max_tokens"]

    if provider == OLLAMA:
        from langchain_ollama import ChatOllama

        if "max_tokens" in kwargs:
            kwargs["num_predict"] = kwargs.pop("max_tokens")
        return ChatOllama(model=model, base_url=settings.ollama_base_url, **kwargs)

    key = api_key_for(settings, provider)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs.setdefault("max_tokens", 8192)
        chat = ChatAnthropic(model=model, api_key=key, **kwargs)
        if ms.get("web_search"):
            chat = chat.bind_tools([{"type": "web_search_20250305", "name": "web_search"}])
        return chat

    from langchain_openai import ChatOpenAI

    if provider in _BASE_URL:
        kwargs["base_url"] = _BASE_URL[provider]
    if provider == "openai" and ms.get("web_search"):
        kwargs["use_responses_api"] = True
    if "reasoning_effort" in ms:
        # Reasoning models spend thousands of output tokens on trivial steps; OpenAI, xAI and OpenRouter all
        # accept the OpenAI-style knob (OpenRouter maps it to each upstream's own setting).
        kwargs["reasoning_effort"] = ms["reasoning_effort"]
    if provider == "openrouter":
        kwargs["default_headers"] = {"HTTP-Referer": "https://github.com/regnull/openbot", "X-Title": "OpenBot"}
        if settings.openrouter_provider_order:
            # Preferred upstreams first (each upstream has its own prompt cache, so staying on one keeps it
            # warm), but fallbacks stay on: a request the preferred upstream cannot serve, e.g. memory
            # extraction's tool_choice=required which Z.AI rejects, must get a cold-cache answer elsewhere
            # rather than "No endpoints found".
            kwargs["extra_body"] = {"provider": {"order": list(settings.openrouter_provider_order), "allow_fallbacks": True}}
        if ms.get("web_search"):
            kwargs.setdefault("extra_body", {})["plugins"] = [{"id": "web"}]
    chat = ChatOpenAI(model=model, api_key=key, **kwargs)
    if ms.get("web_search") and provider == "openai":
        chat = chat.bind_tools([{"type": "web_search_preview"}])
    return chat


def chat_model(bot: BotProfile, settings: Settings) -> BaseChatModel:
    provider, model = effective_bot_profile(bot, settings)
    return provider_chat_model(provider, model, settings, bot.model_settings)


def embeddings(settings: Settings) -> Embeddings | None:
    """None when semantic memory search is off (empty model) or the model's provider is not configured."""
    if not (settings.embedding_model or "").strip():
        return None
    provider, _, model = settings.embedding_model.partition(":")
    if not provider_configured(settings, provider):
        return None
    if provider == OLLAMA:
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(model=model, base_url=settings.ollama_base_url)
    if provider == "openrouter":
        # OpenRouter serves embeddings at /api/v1/embeddings in the OpenAI wire format, so one key can power
        # chat and memory search. Its model names (openai/text-embedding-3-small) are unknown to tiktoken, so
        # the client must not tokenize inputs locally to check their length.
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=model, api_key=api_key_for(settings, provider), base_url=_BASE_URL["openrouter"],
                                check_embedding_ctx_length=False)
    return init_embeddings(settings.embedding_model, api_key=api_key_for(settings, provider))


async def list_ollama_models(settings: Settings, client: httpx.AsyncClient | None) -> list[str] | None:
    """Names of the models installed on the configured Ollama server (GET /api/tags), sorted.

    Returns None when Ollama is not configured, no HTTP client is available, or the server cannot be
    reached in time, so callers can fall back to the static suggestions rather than fail the request."""
    if not settings.ollama_base_url or client is None:
        return None
    url = settings.ollama_base_url.rstrip("/") + "/api/tags"
    try:
        r = await client.get(url, timeout=OLLAMA_TAGS_TIMEOUT)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", []) if isinstance(m, dict) and m.get("name")]
    except Exception as e:  # noqa: BLE001 - any failure here must degrade to the static list
        log.warning("could not list Ollama models from %s: %s", url, e)
        return None
    return sorted(names)


def provider_models(settings: Settings, provider: str, ollama_models: list[str] | None = None) -> list[str]:
    if provider == OLLAMA:
        if ollama_models:
            return list(ollama_models)
        models = PROVIDER_MODELS[OLLAMA]
        return models if settings.ollama_model in models else [settings.ollama_model, *models]
    models = PROVIDER_MODELS[provider]
    if provider != DEFAULT_BOT_PROVIDER:
        return models
    model = configured_bot_model(settings)
    if model in models:
        return models
    return [model, *models]


def provider_default_model(settings: Settings, provider: str, ollama_models: list[str] | None = None) -> str:
    if provider == DEFAULT_BOT_PROVIDER:
        return configured_bot_model(settings)
    if provider == OLLAMA:
        # Prefer a model the server actually has (bare name or name:tag) over an uninstalled default.
        if ollama_models and not any(m == settings.ollama_model or m.split(":", 1)[0] == settings.ollama_model for m in ollama_models):
            return ollama_models[0]
        return settings.ollama_model
    return DEFAULT_MODEL[provider]


def provider_status(settings: Settings, ollama_models: list[str] | None = None) -> list[dict]:
    dp = default_provider(settings)
    auto = {
        "id": AUTO_PROVIDER,
        "configured": dp is not None,
        "models": [],
        "default_model": f"{dp[0]}/{dp[1]}" if dp else "",
    }
    rest = [
        {
            "id": p,
            "configured": provider_configured(settings, p),
            "models": provider_models(settings, p, ollama_models),
            "default_model": provider_default_model(settings, p, ollama_models),
        }
        for p in PROVIDER_ORDER
    ]
    return [auto, *rest]


def default_provider(settings: Settings) -> tuple[str, str] | None:
    if api_key_for(settings, DEFAULT_BOT_PROVIDER):
        return DEFAULT_BOT_PROVIDER, configured_bot_model(settings)
    for p in PROVIDER_ORDER:
        if provider_configured(settings, p):
            return p, provider_default_model(settings, p)
    return None
