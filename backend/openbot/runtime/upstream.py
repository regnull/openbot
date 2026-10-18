"""Sticky OpenRouter upstreams: keep each bot on the upstream that served its last call.

OpenRouter serves a model from many upstreams (34 for glm-5.3-flash) and, unless told otherwise,
spreads calls across them. Each upstream keeps its own prompt cache, so a call landing somewhere new
starts cold: in practice most runs cached only a fixed ~40k prefix while their prompts doubled. An
explicit `openrouter_provider_order` fixes that by hand. Without one, this module does it
automatically: it reads which upstream answered each call and pins the bot's next call to it, with
fallbacks on, so when that upstream fails OpenRouter answers elsewhere and the pin follows.

Staying on one upstream only helps if it caches. OpenRouter's default routing favors the cheapest
upstreams, and on 2026-10-18 bots pinned that way (OpenInference, Venice, PrimeIntellect) got ~2% of
their prompt tokens cached. So the pins also learn: an upstream that keeps serving warm calls (same
upstream as the run's previous call, so the prompt's start should be cached) with little cached is
skipped for that model for a few hours, via OpenRouter's `provider.ignore`, and bots pinned to it
move on until they land on one that caches.

OpenRouter reports the upstream by display name ("Z.AI") but routes by slug ("z-ai"); the model's
public endpoint list maps one to the other.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

log = logging.getLogger(__name__)

UPSTREAM_KEY = "openrouter_provider"
ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"
ENDPOINTS_TTL = 6 * 3600  # upstreams come and go; a stale map only costs a fallback slug
ENDPOINTS_RETRY = 600  # after a failed fetch, guess slugs for this long before asking again
CACHE_HIT_SHARE = 0.25  # a warm call with less than this share of its prompt cached is a miss
MISS_LIMIT = 3  # consecutive warm misses before an upstream is skipped (one summarization rewrite is fine)
IGNORE_TTL = 6 * 3600  # how long a non-caching upstream is skipped before it gets another chance
MAX_IGNORED = 10  # per model; the oldest skip lapses first, so routing never runs out of upstreams


def upstream_of(message: BaseMessage) -> str | None:
    """The OpenRouter upstream that produced `message`, by display name, if it was recorded.

    Stored as a list because streamed chunks' metadata merges by concatenating strings (the
    reason `model_name` reads "z-ai/glm-5.3-flashz-ai/glm-5.3-flash"); lists merge by appending."""
    value = (getattr(message, "response_metadata", None) or {}).get(UPSTREAM_KEY)
    if isinstance(value, list):
        value = value[-1] if value else None
    return value if isinstance(value, str) and value else None


class OpenRouterChatOpenAI(ChatOpenAI):
    """ChatOpenAI that keeps OpenRouter's top-level `provider` field (the upstream that answered),
    which langchain-openai drops, in the reply's response_metadata."""

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        generation = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        if generation is None or not isinstance(chunk, dict):
            return generation
        name = chunk.get("provider")
        # Only on the closing chunks (finish reason or usage), not on every token: each tagged chunk
        # adds one entry to the merged list, which is checkpointed with the message.
        closing = chunk.get("usage") or any(c.get("finish_reason") for c in chunk.get("choices") or [])
        if isinstance(name, str) and name and closing:
            generation.message.response_metadata[UPSTREAM_KEY] = [name]
        return generation

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        raw = response if isinstance(response, dict) else getattr(response, "model_dump", dict)()
        name = raw.get("provider") if isinstance(raw, dict) else None
        if isinstance(name, str) and name:
            for generation in result.generations:
                generation.message.response_metadata[UPSTREAM_KEY] = [name]
        return result


def guess_slug(name: str) -> str:
    """Display name to slug when the endpoint list is unavailable: "Z.AI" -> "z-ai"."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def fetch_endpoint_slugs(model: str) -> dict[str, str]:
    """{display name (lowercased): slug} for `model`'s OpenRouter endpoints. The slug is the first
    segment of the endpoint tag ("deepinfra/fp4" -> "deepinfra"), which routes to any of that
    upstream's endpoints."""
    # Short: a reply waits on this the first time a model's upstream is seen (and every few hours).
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(ENDPOINTS_URL.format(model=model))
        response.raise_for_status()
    slugs = {}
    for endpoint in (response.json().get("data") or {}).get("endpoints") or []:
        name, tag = endpoint.get("provider_name"), endpoint.get("tag")
        if isinstance(name, str) and isinstance(tag, str) and tag:
            slugs.setdefault(name.lower(), tag.split("/", 1)[0])
    return slugs


class UpstreamPins:
    """Per-(bot, model) pinned upstream slug, the cached name-to-slug map per model, and per model the
    upstreams skipped for not caching."""

    def __init__(self, fetch: Callable[[str], Awaitable[dict[str, str]]] = fetch_endpoint_slugs) -> None:
        self._fetch = fetch
        self._pins: dict[tuple[str, str], str] = {}
        self._slugs: dict[str, tuple[float, dict[str, str]]] = {}
        # One lock per model: a slow fetch for one model must not hold up the others' runs.
        self._locks: dict[str, asyncio.Lock] = {}
        self._misses: dict[tuple[str, str, str], int] = {}  # (bot, model, slug) -> consecutive warm misses
        self._ignored: dict[str, dict[str, float]] = {}  # model -> {slug: skipped until (monotonic)}

    def pinned(self, bot_id: str, model: str) -> str | None:
        return self._pins.get((bot_id, model))

    async def slug_for(self, model: str, name: str) -> str:
        async with self._locks.setdefault(model, asyncio.Lock()):
            cached = self._slugs.get(model)
            slugs = cached[1] if cached else {}
            ttl = ENDPOINTS_TTL if slugs else ENDPOINTS_RETRY
            # Never fetched is its own case: monotonic time starts near zero at boot, so a default
            # "fetched at 0" looked fresh for the first ten minutes of a machine's uptime.
            if cached is None or time.monotonic() - cached[0] > ttl:
                try:
                    slugs = await self._fetch(model)
                except Exception as e:  # noqa: BLE001 - a guessed slug is a fine fallback
                    log.warning("could not fetch OpenRouter endpoints for %s: %s", model, e)
                    slugs = {}
                self._slugs[model] = (time.monotonic(), slugs)
        return slugs.get(name.lower()) or guess_slug(name)

    def _others_remain(self, model: str, slug: str) -> bool:
        """Whether skipping `slug` still leaves `model` an upstream to route to. Unknown when the
        endpoint list could not be fetched; then nothing is skipped, since an ignore list covering
        every upstream would fail every call to the model with "no endpoints"."""
        cached = self._slugs.get(model)
        known = set(cached[1].values()) if cached else set()
        return bool(known - set(self.ignored(model)) - {slug})

    def ignored(self, model: str) -> list[str]:
        """Upstreams currently skipped for `model`, expired skips dropped."""
        entries = self._ignored.get(model, {})
        now = time.monotonic()
        for slug in [s for s, until in entries.items() if until <= now]:
            del entries[slug]
        return sorted(entries)

    def observe_cache(self, bot_id: str, model: str, slug: str, cacheable_tokens: int, cached_tokens: int) -> None:
        """Judge one warm call by one bot. `cacheable_tokens` is what the upstream could have had
        cached: the part of this prompt the previous call already sent, not the whole prompt (a 30k
        tool result can only be cached from the call after it). A hit clears the bot's miss streak;
        MISS_LIMIT misses in a row skip the upstream for this model and unpin every bot pinned to it.
        Streaks are per bot, so one bot's hit does not hide another's misses, nor do ordinary misses
        from several bots add up to a skip."""
        key = (bot_id, model, slug)
        if cacheable_tokens <= 0 or cached_tokens >= CACHE_HIT_SHARE * cacheable_tokens:
            self._misses.pop(key, None)
            return
        self._misses[key] = self._misses.get(key, 0) + 1
        if self._misses[key] < MISS_LIMIT:
            return
        del self._misses[key]
        if not self._others_remain(model, slug):
            log.info("OpenRouter upstream %s barely caches %s, but it is the last one left: keeping it", slug, model)
            return
        entries = self._ignored.setdefault(model, {})
        entries[slug] = time.monotonic() + IGNORE_TTL
        while len(entries) > MAX_IGNORED:
            del entries[min(entries, key=entries.__getitem__)]
        for pin_key in [k for k, v in self._pins.items() if k[1] == model and v == slug]:
            del self._pins[pin_key]
        log.info(
            "OpenRouter upstream %s barely caches %s (%d warm misses in a row): skipping it for %dh",
            slug, model, MISS_LIMIT, IGNORE_TTL // 3600,
        )

    async def record(self, bot_id: str, model: str, name: str) -> str:
        slug = await self.slug_for(model, name)
        previous = self._pins.get((bot_id, model))
        if previous != slug:
            log.info("bot %s on %s: pinning OpenRouter upstream %s (was %s)", bot_id, model, slug, previous)
        self._pins[(bot_id, model)] = slug
        return slug


def _reply(response: Any) -> AIMessage | None:
    if isinstance(response, AIMessage):
        return response
    for message in reversed(getattr(response, "result", None) or []):
        if isinstance(message, AIMessage):
            return message
    return None


class StickyUpstreamMiddleware(AgentMiddleware):
    """Routes each OpenRouter call to the upstream that served the bot's previous one, unless the
    operator set `openrouter_provider_order` (an explicit choice always wins)."""

    def __init__(self, pins: UpstreamPins, bot_id: str, model: str, settings) -> None:
        super().__init__()
        self.pins, self.bot_id, self.model, self.settings = pins, bot_id, model, settings
        # One middleware per run: the upstream of this run's previous call, to tell warm calls apart.
        self._last_slug: str | None = None
        self._last_prompt = 0  # input tokens of that call: the most a warm call can have cached

    def _explicit(self) -> bool:
        return bool(getattr(self.settings, "openrouter_provider_order", None))

    def _pinned(self, request: ModelRequest) -> ModelRequest:
        if self._explicit():
            return request
        slug = self.pins.pinned(self.bot_id, self.model)
        ignored = self.pins.ignored(self.model)
        if slug in ignored:
            # A call still in flight when its upstream was skipped re-pinned the bot to it.
            slug = None
        provider: dict[str, Any] = {}
        if slug is not None:
            provider.update(order=[slug], allow_fallbacks=True)
        if ignored:
            provider["ignore"] = ignored
        if not provider:
            return request
        # bind(extra_body=...) replaces the model's own extra_body wholesale, so carry over what it
        # already sends (e.g. the web-search plugin).
        extra = {
            **(getattr(request.model, "extra_body", None) or {}),
            **(request.model_settings.get("extra_body") or {}),
            "provider": provider,
        }
        return request.override(model_settings={**request.model_settings, "extra_body": extra})

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Any]) -> Any:
        return handler(self._pinned(request))

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[Any]]
    ) -> Any:
        response = await handler(self._pinned(request))
        reply = _reply(response)
        name = upstream_of(reply) if reply is not None else None
        if name and not self._explicit():
            slug = await self.pins.record(self.bot_id, self.model, name)
            usage = getattr(reply, "usage_metadata", None) or {}
            prompt = int(usage.get("input_tokens") or 0)
            if slug == self._last_slug and usage:
                cached = int((usage.get("input_token_details") or {}).get("cache_read") or 0)
                self.pins.observe_cache(self.bot_id, self.model, slug, min(prompt, self._last_prompt), cached)
            self._last_slug, self._last_prompt = slug, prompt
        return response
