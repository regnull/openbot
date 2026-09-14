from __future__ import annotations

from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from openbot.config import Settings
from openbot.db.models import BotProfile

PROVIDER_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5-mini"],
    "anthropic": ["claude-sonnet-5", "claude-opus-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"],
    "openrouter": ["anthropic/claude-sonnet-5", "openai/gpt-5.5", "x-ai/grok-4.6", "openai/gpt-oss-120b"],
    "xai": ["grok-4.6", "grok-4.5"],
}
DEFAULT_MODEL = {p: models[0] for p, models in PROVIDER_MODELS.items()}
PROVIDER_ORDER = ["openai", "anthropic", "openrouter", "xai"]
_KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
            "openrouter": "OPENROUTER_API_KEY", "xai": "XAI_API_KEY"}
_BASE_URL = {"openrouter": "https://openrouter.ai/api/v1", "xai": "https://api.x.ai/v1"}


def api_key_for(settings: Settings, provider: str) -> str | None:
    return getattr(settings, f"{provider}_api_key", None)


def chat_model(bot: BotProfile, settings: Settings) -> BaseChatModel:
    key = api_key_for(settings, bot.provider)
    if not key:
        raise ValueError(f"provider {bot.provider} is not configured: set {_KEY_ENV[bot.provider]}")
    ms = dict(bot.model_settings or {})

    if bot.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        model = ChatAnthropic(model=bot.model, api_key=key, max_tokens=ms.get("max_tokens", 8192))
    else:
        from langchain_openai import ChatOpenAI
        kwargs: dict = {}
        if bot.provider in _BASE_URL:
            kwargs["base_url"] = _BASE_URL[bot.provider]
        if bot.provider == "openrouter":
            kwargs["default_headers"] = {"HTTP-Referer": "https://github.com/regnull/openbot", "X-Title": "OpenBot"}
        if "max_tokens" in ms:
            kwargs["max_tokens"] = ms["max_tokens"]
        model = ChatOpenAI(model=bot.model, api_key=key, **kwargs)

    # Assigned post-construction (rather than passed to __init__) because some
    # provider SDKs run model-name-dependent validation at construction time that
    # silently strips an explicitly-requested temperature (e.g. langchain-openai
    # clears `temperature` for "gpt-5*" reasoning models unless reasoning_effort
    # is disabled). Assigning the attribute afterwards does not re-run that
    # validator, so an operator-configured temperature always takes effect.
    if "temperature" in ms:
        model.temperature = ms["temperature"]
    return model


def embeddings(settings: Settings) -> Embeddings | None:
    provider = settings.embedding_model.split(":", 1)[0]
    key = api_key_for(settings, provider)
    if not key:
        return None
    return init_embeddings(settings.embedding_model, api_key=key)


def provider_status(settings: Settings) -> list[dict]:
    return [{"id": p, "configured": bool(api_key_for(settings, p)), "models": PROVIDER_MODELS[p],
             "default_model": DEFAULT_MODEL[p]} for p in PROVIDER_ORDER]


def default_provider(settings: Settings) -> tuple[str, str] | None:
    for p in PROVIDER_ORDER:
        if api_key_for(settings, p):
            return p, DEFAULT_MODEL[p]
    return None
