from __future__ import annotations

from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from openbot.config import Settings
from openbot.db.models import BotProfile

DEFAULT_BOT_PROVIDER = "openrouter"
DEFAULT_BOT_MODEL = "openai/gpt-4o-mini"

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
}
DEFAULT_MODEL = {p: models[0] for p, models in PROVIDER_MODELS.items()}
PROVIDER_ORDER = ["openai", "anthropic", "openrouter", "xai"]
_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "xai": "XAI_API_KEY",
}
_BASE_URL = {"openrouter": "https://openrouter.ai/api/v1", "xai": "https://api.x.ai/v1"}


def api_key_for(settings: Settings, provider: str) -> str | None:
    return getattr(settings, f"{provider}_api_key", None)


def configured_bot_model(settings: Settings) -> str:
    return settings.bot_model or settings.openrouter_model or DEFAULT_BOT_MODEL


def effective_bot_profile(bot: BotProfile, settings: Settings) -> tuple[str, str]:
    """Return the provider/model to use for a bot LLM call.

    A configured OpenRouter key makes OpenRouter the runtime provider for every bot, so the team can
    be moved to another OpenRouter model from `.env` without editing persisted bot rows one by one.
    Installations without OpenRouter configured keep using each bot's stored provider/model.
    """
    if settings.bot_model or settings.openrouter_model or api_key_for(settings, DEFAULT_BOT_PROVIDER):
        return DEFAULT_BOT_PROVIDER, configured_bot_model(settings)
    return bot.provider, bot.model


def chat_model(bot: BotProfile, settings: Settings) -> BaseChatModel:
    provider, model = effective_bot_profile(bot, settings)
    key = api_key_for(settings, provider)
    if not key:
        raise ValueError(f"provider {provider} is not configured: set {_KEY_ENV[provider]}")
    ms = dict(bot.model_settings or {})
    kwargs: dict = {}
    if "temperature" in ms:
        kwargs["temperature"] = ms["temperature"]
    if "max_tokens" in ms:
        kwargs["max_tokens"] = ms["max_tokens"]

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs.setdefault("max_tokens", 8192)
        return ChatAnthropic(model=model, api_key=key, **kwargs)

    from langchain_openai import ChatOpenAI

    if provider in _BASE_URL:
        kwargs["base_url"] = _BASE_URL[provider]
    if provider == "openrouter":
        kwargs["default_headers"] = {"HTTP-Referer": "https://github.com/regnull/openbot", "X-Title": "OpenBot"}
    return ChatOpenAI(model=model, api_key=key, **kwargs)


def embeddings(settings: Settings) -> Embeddings | None:
    provider = settings.embedding_model.split(":", 1)[0]
    key = api_key_for(settings, provider)
    if not key:
        return None
    return init_embeddings(settings.embedding_model, api_key=key)


def provider_models(settings: Settings, provider: str) -> list[str]:
    models = PROVIDER_MODELS[provider]
    if provider != DEFAULT_BOT_PROVIDER:
        return models
    model = configured_bot_model(settings)
    if model in models:
        return models
    return [model, *models]


def provider_status(settings: Settings) -> list[dict]:
    return [
        {
            "id": p,
            "configured": bool(api_key_for(settings, p)),
            "models": provider_models(settings, p),
            "default_model": configured_bot_model(settings) if p == DEFAULT_BOT_PROVIDER else DEFAULT_MODEL[p],
        }
        for p in PROVIDER_ORDER
    ]


def default_provider(settings: Settings) -> tuple[str, str] | None:
    if api_key_for(settings, DEFAULT_BOT_PROVIDER):
        return DEFAULT_BOT_PROVIDER, configured_bot_model(settings)
    for p in PROVIDER_ORDER:
        if api_key_for(settings, p):
            return p, DEFAULT_MODEL[p]
    return None
