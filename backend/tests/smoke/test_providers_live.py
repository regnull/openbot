"""Live provider smoke tests.

These hit the real provider APIs and cost a few tokens, so every test skips unless the matching
key is configured. `Settings()` here deliberately reads the real env files (`.env`, then `../.env`
so running from `backend/` picks up the repo-root file), unlike the rest of the suite which passes
`_env_file=None`. In CI no keys are set, so the whole module skips.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from openbot.config import Settings
from openbot.db.models import BotProfile
from openbot.runtime.providers import DEFAULT_MODEL, PROVIDER_MODELS, api_key_for, chat_model

pytestmark = pytest.mark.smoke

PROVIDERS = ["openai", "anthropic", "openrouter", "xai"]
ALL_MODELS = [(p, m) for p in PROVIDERS for m in PROVIDER_MODELS[p]]


def _settings_or_skip(provider: str) -> Settings:
    settings = Settings()
    if not api_key_for(settings, provider):
        pytest.skip(f"{provider} key not configured")
    return settings


# Reasoning models (gpt-5-mini, claude-opus-5, openai/gpt-oss-120b) spend their whole budget on
# reasoning tokens and return empty content if `max_tokens` is tiny, so keep it above the reasoning
# floor rather than at the ~20 a one-word answer needs.
MAX_TOKENS = 256


async def _say_ok(provider: str, model: str, settings: Settings) -> str:
    chat = chat_model(
        BotProfile(provider=provider, model=model, model_settings={"max_tokens": MAX_TOKENS}),
        settings,
    )
    out = await chat.ainvoke([HumanMessage(content="Reply with the single word OK.")])
    return out.text if isinstance(out.text, str) else out.text()


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_provider_roundtrip(provider: str):
    """The curated default model for each configured provider answers a trivial prompt."""
    settings = _settings_or_skip(provider)
    assert "OK" in (await _say_ok(provider, DEFAULT_MODEL[provider], settings)).upper()


@pytest.mark.parametrize(("provider", "model"), ALL_MODELS, ids=[f"{p}:{m}" for p, m in ALL_MODELS])
async def test_curated_model_id_is_valid(provider: str, model: str):
    """Every model id offered in the UI dropdown is accepted by its provider."""
    settings = _settings_or_skip(provider)
    assert "OK" in (await _say_ok(provider, model, settings)).upper()
