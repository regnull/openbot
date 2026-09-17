"""Runtime-editable settings, layered over the environment.

`.env` holds only what the process needs before it can read its own database (see
docs/superpowers/specs/2026-09-17-setup-wizard-design.md). Everything an operator configures lives
here: provider keys, Ollama, embeddings, the default model, and the tunables for run limits, context
management, memory and model routing. An override is stored in `app_settings` (secrets encrypted with
the secret key), applied to the live `Settings` object (which providers, the runner and tools read at
call time, so the next call sees it), and re-applied at every startup. Precedence: stored override,
then environment, then the built-in default.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from openbot.config import Settings
from openbot.db.models import AppSetting, utcnow

log = logging.getLogger(__name__)

MASK = "••••••••"


@dataclass(frozen=True)
class Tunable:
    group: str
    label: str
    description: str
    minimum: float | None = None   # inclusive lower bound for numbers
    secret: bool = False           # encrypted at rest, masked in the API


TUNABLES: dict[str, Tunable] = {
    # --- Providers: what the setup wizard asks for first --------------------------------------------------
    "openrouter_api_key": Tunable("Providers", "OpenRouter API key",
        "Gives access to most models through one key; the default for bots on the auto provider.", secret=True),
    "openai_api_key": Tunable("Providers", "OpenAI API key",
        "Chat models and the default embedding model (text-embedding-3-small).", secret=True),
    "anthropic_api_key": Tunable("Providers", "Anthropic API key",
        "Claude models; also lets OpenRouter anthropic/... models go direct for full prompt caching.", secret=True),
    "xai_api_key": Tunable("Providers", "xAI API key", "Grok models.", secret=True),
    "ollama_base_url": Tunable("Providers", "Ollama base URL",
        "A local Ollama server, e.g. http://localhost:11434. Setting it enables the ollama provider; no key needed."),
    "ollama_model": Tunable("Providers", "Ollama default model", "Model offered first for bots on the ollama provider."),
    # --- Embeddings ----------------------------------------------------------------------------------------
    "embedding_model": Tunable("Embeddings", "Embedding model",
        "provider:model for semantic memory search, e.g. openai:text-embedding-3-small or ollama:nomic-embed-text. "
        "Leave empty to turn semantic search off (memory still works by recency). Applies immediately."),
    "embedding_dims": Tunable("Embeddings", "Embedding dimensions",
        "Must match the model: 1536 for text-embedding-3-small, 768 for nomic-embed-text.", 1),
    # --- Run limits ------------------------------------------------------------------------------------------
    "max_model_calls_per_run": Tunable("Run limits", "Model calls per run",
        "Model turns a run may make before the agent is stopped and posts a notice. A bot can lower it for itself in its model settings.", 1),
    "max_bot_hops": Tunable("Run limits", "Bot-to-bot hop limit",
        "Consecutive bot-to-bot hand-offs allowed before the thread pauses for a human message.", 1),
    # --- Context ---------------------------------------------------------------------------------------------
    "history_token_budget": Tunable("Context", "History token budget",
        "Approximate tokens of thread history included in each run's prompt.", 1000),
    "history_max_messages": Tunable("Context", "History max messages",
        "Most recent thread messages included in each run's prompt.", 1),
    "tool_output_cap": Tunable("Context", "Tool output cap (chars)",
        "Longest single tool result the model sees; longer results are shortened and say so.", 500),
    "shell_output_cap": Tunable("Context", "Shell output cap (chars)",
        "Tighter cap for run_shell, so dumping a file through the shell loses to read_file with a line range.", 500),
    "context_trigger_tokens": Tunable("Context", "Clear old tool results above (tokens)",
        "Once a run's context passes this, old tool results and their call arguments are replaced by a placeholder.", 1000),
    "context_clear_at_least": Tunable("Context", "Reclaim at least (tokens)",
        "Each clearing frees at least this much, so clearings are rare and the provider's prompt cache stays warm.", 0),
    "summary_trigger_tokens": Tunable("Context", "Summarize history above (tokens)",
        "Once a run's context passes this, older history is folded into one summary message by the bot's own model.", 1000),
    "summary_keep_messages": Tunable("Context", "Summary keeps last (messages)",
        "How many recent messages summarization leaves verbatim.", 2),
    # --- Memory ----------------------------------------------------------------------------------------------
    "memory_reflection_delay": Tunable("Memory", "Reflection delay (seconds)",
        "How long after a run ends before its transcript is mined for durable memories; runs in the same thread within this window reflect once.", 0),
    # --- Model routing ---------------------------------------------------------------------------------------
    "bot_model": Tunable("Model routing", "Default bot model",
        "OpenRouter model used by every bot on the auto provider (provider/model id)."),
    "openrouter_provider_order": Tunable("Model routing", "Preferred OpenRouter upstreams",
        "Comma-separated upstream slugs to try first (each has its own prompt cache); others are fallbacks."),
    "prompt_caching": Tunable("Model routing", "Prompt caching", "Add cache breakpoints to every Anthropic model call."),
    "direct_anthropic": Tunable("Model routing", "Direct Anthropic routing",
        "Send OpenRouter anthropic/... models straight to Anthropic when a key is configured, so caching covers tool results too."),
}

EMBEDDING_KEYS = ("embedding_model", "embedding_dims")
_TYPE_NAMES = {int: "int", float: "float", bool: "bool", str: "str"}


def field_type(key: str) -> str:
    if TUNABLES[key].secret:
        return "secret"
    ann = Settings.model_fields[key].annotation
    origin = getattr(ann, "__origin__", None)
    if origin is list or "list" in str(ann):
        return "list"
    for t, name in _TYPE_NAMES.items():
        if ann is t or (getattr(ann, "__args__", None) and t in ann.__args__):
            return name
    return "str"


def _optional(key: str) -> bool:
    return "None" in str(Settings.model_fields[key].annotation)


def coerce(key: str, value: Any) -> Any:
    """Validate one override the way the environment would, plus the tunable's range."""
    if key not in TUNABLES:
        raise ValueError(f"{key} is not a runtime-editable setting")
    kind = field_type(key)
    if kind == "list" and isinstance(value, str):
        value = [p.strip() for p in value.split(",") if p.strip()]
    if kind == "bool" and not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    if kind in ("int", "float") and isinstance(value, bool | str):
        raise ValueError(f"{key} must be a number")
    if kind in ("str", "secret"):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        if isinstance(value, str):
            value = value.strip()
        if value == "" and _optional(key):
            value = None                           # an empty optional string means "unset"
    try:
        value = TypeAdapter(Settings.model_fields[key].annotation).validate_python(value)
    except ValidationError as e:
        raise ValueError(f"{key}: {e.errors()[0].get('msg', 'invalid value')}") from e
    minimum = TUNABLES[key].minimum
    if minimum is not None and isinstance(value, int | float) and value < minimum:
        raise ValueError(f"{key} must be at least {minimum:g}")
    return value


# --- storage -------------------------------------------------------------------------------------------------

def _to_stored(services, key: str, value: Any) -> Any:
    if TUNABLES[key].secret and value is not None:
        return {"enc": services.secrets.encrypt(str(value))}
    return value


def _from_stored(services, key: str, stored: Any) -> Any:
    if TUNABLES[key].secret and isinstance(stored, dict) and "enc" in stored:
        if services is None or services.secrets is None:
            return None
        plain = services.secrets.decrypt(stored["enc"])
        if plain is None:
            log.warning("stored setting %s cannot be decrypted with the current secret key; ignoring it", key)
        return plain
    return stored


async def load_overrides(session_factory: async_sessionmaker, services=None) -> dict[str, Any]:
    """Stored overrides by key. Secrets are decrypted when `services` (with its SecretBox) is given,
    otherwise returned in their stored, encrypted form."""
    async with session_factory() as session:
        rows = (await session.execute(select(AppSetting))).scalars().all()
    return {r.key: _from_stored(services, r.key, r.value) for r in rows if r.key in TUNABLES}


# --- applying ------------------------------------------------------------------------------------------------

def _apply(services, key: str, value: Any) -> None:
    setattr(services.settings, key, value)
    if key == "memory_reflection_delay" and services.reflector is not None:
        services.reflector.delay = value


async def _after_change(services, keys: set[str]) -> None:
    """Side effects of a settings change: embeddings reopen the memory store; meeting the minimum
    configuration seeds the demo team (boot skips seeding while no provider is configured)."""
    if keys & set(EMBEDDING_KEYS):
        from openbot.runtime.persistence import reopen_memory_store
        try:
            await reopen_memory_store(services)
        except Exception:
            log.exception("could not reopen the memory store with the new embedding settings")
    if services.settings.seed_demo_bots:
        from openbot.runtime.setup import setup_status
        from openbot.seed import seed_demo_bots
        if setup_status(services.settings)["complete"]:
            await seed_demo_bots(services)


async def apply_stored_overrides(services) -> dict[str, Any]:
    """Snapshot the environment values, then lay the stored overrides over them. Run once at startup."""
    services.env_defaults = {k: getattr(services.settings, k) for k in TUNABLES}
    overrides = await load_overrides(services.session_factory, services)
    for key, value in overrides.items():
        if value is None and TUNABLES[key].secret:
            continue                                   # undecryptable: keep the environment value
        try:
            _apply(services, key, coerce(key, value))
        except ValueError as e:
            log.warning("ignoring stored setting %s=%r: %s", key, value, e)
    if overrides:
        shown = ", ".join(f"{k}={'<secret>' if TUNABLES[k].secret else repr(v)}" for k, v in overrides.items())
        log.info("runtime settings overriding the environment: %s", shown)
    return overrides


async def update_settings(services, updates: dict[str, Any]) -> None:
    """Validate the whole batch first, then persist and apply; a bad key leaves nothing changed. A masked
    secret value (what the UI shows) is a no-op for that key."""
    updates = {k: v for k, v in updates.items() if not (k in TUNABLES and TUNABLES[k].secret and v == MASK)}
    clean = {k: coerce(k, v) for k, v in updates.items()}
    async with services.session_factory() as session:
        for key, value in clean.items():
            stored = _to_stored(services, key, value)
            row = await session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value=stored, updated_at=utcnow()))
            else:
                row.value, row.updated_at = stored, utcnow()
        await session.commit()
    for key, value in clean.items():
        _apply(services, key, value)
    if clean:
        shown = ", ".join(f"{k}={'<secret>' if TUNABLES[k].secret else repr(v)}" for k, v in clean.items())
        log.info("runtime settings updated: %s", shown)
        await _after_change(services, set(clean))


async def reset_setting(services, key: str) -> None:
    if key not in TUNABLES:
        raise ValueError(f"{key} is not a runtime-editable setting")
    async with services.session_factory() as session:
        row = await session.get(AppSetting, key)
        if row is not None:
            await session.delete(row)
            await session.commit()
    _apply(services, key, services.env_defaults.get(key, getattr(services.settings, key)))
    await _after_change(services, {key})


async def describe(services) -> list[dict[str, Any]]:
    overrides = await load_overrides(services.session_factory)
    defaults = getattr(services, "env_defaults", None) or {k: getattr(services.settings, k) for k in TUNABLES}
    out = []
    for key, t in TUNABLES.items():
        value, default = getattr(services.settings, key), defaults.get(key)
        row = {"key": key, "group": t.group, "label": t.label, "description": t.description, "type": field_type(key),
               "overridden": key in overrides, "secret": t.secret, "is_set": value not in (None, "")}
        if t.secret:
            row["value"], row["default"] = (MASK if value else None), (MASK if default else None)
        else:
            row["value"], row["default"] = value, default
        out.append(row)
    return out
