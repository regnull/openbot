"""Runtime-editable settings, layered over the environment.

The environment (`.env`) stays the place for secrets and infrastructure. The tunables listed here are
the knobs an operator adjusts while the system runs: run limits, context management, memory, model
routing. An override is stored in `app_settings`, applied to the live `Settings` object (which the
runner and tools read at call time, so the next run sees it), and re-applied at every startup.
Precedence: stored override, then environment, then the built-in default.
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


@dataclass(frozen=True)
class Tunable:
    group: str
    label: str
    description: str
    minimum: float | None = None   # inclusive lower bound for numbers


TUNABLES: dict[str, Tunable] = {
    "max_model_calls_per_run": Tunable("Run limits", "Model calls per run",
        "Model turns a run may make before the agent is stopped and posts a notice. A bot can lower it for itself in its model settings.", 1),
    "max_bot_hops": Tunable("Run limits", "Bot-to-bot hop limit",
        "Consecutive bot-to-bot hand-offs allowed before the thread pauses for a human message.", 1),
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
    "memory_reflection_delay": Tunable("Memory", "Reflection delay (seconds)",
        "How long after a run ends before its transcript is mined for durable memories; runs in the same thread within this window reflect once.", 0),
    "bot_model": Tunable("Model routing", "Default bot model",
        "OpenRouter model used by every bot on the auto provider (provider/model id).", None),
    "openrouter_provider_order": Tunable("Model routing", "Preferred OpenRouter upstreams",
        "Comma-separated upstream slugs to try first (each has its own prompt cache); others are fallbacks.", None),
    "prompt_caching": Tunable("Model routing", "Prompt caching",
        "Add cache breakpoints to every Anthropic model call.", None),
    "direct_anthropic": Tunable("Model routing", "Direct Anthropic routing",
        "Send OpenRouter anthropic/... models straight to Anthropic when a key is configured, so caching covers tool results too.", None),
}

_TYPE_NAMES = {int: "int", float: "float", bool: "bool", str: "str"}


def field_type(key: str) -> str:
    ann = Settings.model_fields[key].annotation
    origin = getattr(ann, "__origin__", None)
    if origin is list or "list" in str(ann):
        return "list"
    for t, name in _TYPE_NAMES.items():
        if ann is t or (getattr(ann, "__args__", None) and t in ann.__args__):
            return name
    return "str"


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
    if kind == "str" and value is not None and not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    try:
        value = TypeAdapter(Settings.model_fields[key].annotation).validate_python(value)
    except ValidationError as e:
        raise ValueError(f"{key}: {e.errors()[0].get('msg', 'invalid value')}") from e
    minimum = TUNABLES[key].minimum
    if minimum is not None and isinstance(value, int | float) and value < minimum:
        raise ValueError(f"{key} must be at least {minimum:g}")
    return value


async def load_overrides(session_factory: async_sessionmaker) -> dict[str, Any]:
    async with session_factory() as session:
        rows = (await session.execute(select(AppSetting))).scalars().all()
    return {r.key: r.value for r in rows if r.key in TUNABLES}


def _apply(services, key: str, value: Any) -> None:
    setattr(services.settings, key, value)
    if key == "memory_reflection_delay" and services.reflector is not None:
        services.reflector.delay = value


async def apply_stored_overrides(services) -> dict[str, Any]:
    """Snapshot the environment values, then lay the stored overrides over them. Run once at startup."""
    services.env_defaults = {k: getattr(services.settings, k) for k in TUNABLES}
    overrides = await load_overrides(services.session_factory)
    for key, value in overrides.items():
        try:
            _apply(services, key, coerce(key, value))
        except ValueError as e:
            log.warning("ignoring stored setting %s=%r: %s", key, value, e)
    if overrides:
        log.info("runtime settings overriding the environment: %s", ", ".join(f"{k}={v!r}" for k, v in overrides.items()))
    return overrides


async def update_settings(services, updates: dict[str, Any]) -> None:
    """Validate the whole batch first, then persist and apply; a bad key leaves nothing changed."""
    clean = {k: coerce(k, v) for k, v in updates.items()}
    async with services.session_factory() as session:
        for key, value in clean.items():
            row = await session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value=value, updated_at=utcnow()))
            else:
                row.value, row.updated_at = value, utcnow()
        await session.commit()
    for key, value in clean.items():
        _apply(services, key, value)
    log.info("runtime settings updated: %s", ", ".join(f"{k}={v!r}" for k, v in clean.items()))


async def reset_setting(services, key: str) -> None:
    if key not in TUNABLES:
        raise ValueError(f"{key} is not a runtime-editable setting")
    async with services.session_factory() as session:
        row = await session.get(AppSetting, key)
        if row is not None:
            await session.delete(row)
            await session.commit()
    _apply(services, key, services.env_defaults.get(key, getattr(services.settings, key)))


async def describe(services) -> list[dict[str, Any]]:
    overrides = await load_overrides(services.session_factory)
    defaults = getattr(services, "env_defaults", None) or {k: getattr(services.settings, k) for k in TUNABLES}
    return [{"key": key, "group": t.group, "label": t.label, "description": t.description, "type": field_type(key),
             "value": getattr(services.settings, key), "default": defaults.get(key), "overridden": key in overrides}
            for key, t in TUNABLES.items()]
