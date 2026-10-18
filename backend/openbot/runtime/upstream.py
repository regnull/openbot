"""Sticky OpenRouter upstreams: keep each bot on the upstream that served its last call.

OpenRouter serves a model from many upstreams (34 for glm-5.3-flash) and, unless told otherwise,
spreads calls across them. Each upstream keeps its own prompt cache, so a call landing somewhere new
starts cold: in practice most runs cached only a fixed ~40k prefix while their prompts doubled. An
explicit `openrouter_provider_order` fixes that by hand. Without one, this module does it
automatically: it reads which upstream answered each call and pins the bot's next call to it, with
fallbacks on, so when that upstream fails OpenRouter answers elsewhere and the pin follows.

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
    """Per-(bot, model) pinned upstream slug, plus the cached name-to-slug map per model."""

    def __init__(self, fetch: Callable[[str], Awaitable[dict[str, str]]] = fetch_endpoint_slugs) -> None:
        self._fetch = fetch
        self._pins: dict[tuple[str, str], str] = {}
        self._slugs: dict[str, tuple[float, dict[str, str]]] = {}
        # One lock per model: a slow fetch for one model must not hold up the others' runs.
        self._locks: dict[str, asyncio.Lock] = {}

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

    def _explicit(self) -> bool:
        return bool(getattr(self.settings, "openrouter_provider_order", None))

    def _pinned(self, request: ModelRequest) -> ModelRequest:
        slug = None if self._explicit() else self.pins.pinned(self.bot_id, self.model)
        if slug is None:
            return request
        # bind(extra_body=...) replaces the model's own extra_body wholesale, so carry over what it
        # already sends (e.g. the web-search plugin).
        extra = {
            **(getattr(request.model, "extra_body", None) or {}),
            **(request.model_settings.get("extra_body") or {}),
            "provider": {"order": [slug], "allow_fallbacks": True},
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
            await self.pins.record(self.bot_id, self.model, name)
        return response
