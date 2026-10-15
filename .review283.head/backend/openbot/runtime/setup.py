"""Is this install configured well enough to do useful work? Drives the first-run wizard.

Minimum: one usable chat provider (an API key, or an Ollama base URL) and an explicit embeddings
choice (a model whose provider is configured, or an empty model meaning semantic memory search is
off). Values come from the live `Settings`, so database overrides and `.env` both count.
"""
from __future__ import annotations

from openbot.runtime.providers import PROVIDER_ORDER, provider_configured

CHAT_PROVIDERS = tuple(PROVIDER_ORDER)


def _configured(settings, provider: str) -> bool:
    try:
        return bool(provider) and provider_configured(settings, provider)
    except (KeyError, ValueError):
        return False


def setup_status(settings) -> dict:
    providers = [p for p in CHAT_PROVIDERS if _configured(settings, p)]
    model = (settings.embedding_model or "").strip()
    if not model:
        embeddings = {"ok": True, "model": "", "reason": "semantic memory search is off"}
    else:
        provider = model.partition(":")[0]
        ok = _configured(settings, provider)
        embeddings = {"ok": ok, "model": model,
                      "reason": None if ok else f"the embedding model uses provider {provider!r}, which has no key or URL configured"}
    missing = [name for name, ok in (("chat", bool(providers)), ("embeddings", embeddings["ok"])) if not ok]
    return {"complete": not missing, "chat": {"ok": bool(providers), "providers": providers}, "embeddings": embeddings,
            "missing": missing}
