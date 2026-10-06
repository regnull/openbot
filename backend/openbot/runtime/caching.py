"""Prompt caching for bot runs.

Every model turn of an agent loop re-sends the whole transcript so far, so without caching the cost
of a run grows with the square of its length. Anthropic models cache any prefix that ends at a
`cache_control` breakpoint; the breakpoint has to be present in the request.

- Direct Anthropic (`ChatAnthropic`): LangChain's `AnthropicPromptCachingMiddleware` tags the system
  prompt, the tool definitions and (via a model setting) the latest message, so the entire growing
  transcript, tool results included, is cached turn over turn.
- Anthropic models through OpenRouter (`ChatOpenAI` against openrouter.ai): the OpenAI-compatible
  client keeps `cache_control` on system and user text blocks but strips it from tool messages, so
  the best we can do is cache the system prompt, tool definitions and the conversation up to the
  latest human message. `OpenRouterPromptCacheMiddleware` adds those breakpoints. The provider layer
  prefers the direct Anthropic route when an Anthropic key is configured for exactly this reason.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

CACHE_CONTROL = {"type": "ephemeral"}
OPENROUTER_HOST = "openrouter.ai"


def _tag_blocks(content: str | list) -> list | None:
    """Return `content` as a list of blocks with cache_control on the last text block, or None if
    there is no text to tag (an empty text block is rejected by Anthropic)."""
    if isinstance(content, str):
        if not content.strip():
            return None
        return [{"type": "text", "text": content, "cache_control": CACHE_CONTROL}]
    blocks = [dict(b) if isinstance(b, dict) else {"type": "text", "text": str(b)} for b in content]
    for b in reversed(blocks):
        if b.get("type") == "text" and str(b.get("text", "")).strip():
            b["cache_control"] = CACHE_CONTROL
            return blocks
    return None


def _tag_system_blocks(content: str | list, cache_control: dict[str, str]) -> list | None:
    if isinstance(content, str):
        return _tag_blocks(content)
    blocks = [dict(b) if isinstance(b, dict) else {"type": "text", "text": str(b)} for b in content]
    text_blocks = [b for b in blocks if b.get("type") == "text" and str(b.get("text", "")).strip()]
    if not text_blocks:
        return None
    for block in text_blocks[:2]:
        block["cache_control"] = cache_control
    return blocks


def _tagged(message: BaseMessage) -> BaseMessage | None:
    blocks = _tag_blocks(message.content)
    if blocks is None:
        return None
    return message.model_copy(update={"content": blocks})


class AnthropicPromptCacheMiddleware(AnthropicPromptCachingMiddleware):
    """Cache both stable and dynamic system-prompt blocks for direct Anthropic calls."""

    def _apply_caching(self, request: ModelRequest) -> ModelRequest:
        request = super()._apply_caching(request)
        message = request.system_message
        if not isinstance(message, SystemMessage) or not isinstance(message.content, list):
            return request
        blocks = _tag_system_blocks(message.content, self._cache_control)
        return request.override(system_message=message.model_copy(update={"content": blocks})) if blocks else request


# Adapted from OpenCode's MIT-licensed prompt-cache breakpoint strategy.
class OpenRouterPromptCacheMiddleware(AgentMiddleware):
    """Add Anthropic cache breakpoints to requests sent through an OpenAI-compatible endpoint.

    Tags the system message and the most recent human message; tool messages cannot carry the
    breakpoint through this client, so tool results inside the current turn are not cached."""

    def _apply(self, request: ModelRequest) -> ModelRequest:
        overrides: dict[str, Any] = {}
        if isinstance(request.system_message, SystemMessage):
            blocks = _tag_system_blocks(request.system_message.content, CACHE_CONTROL)
            if blocks is not None:
                overrides["system_message"] = request.system_message.model_copy(update={"content": blocks})
        messages = list(request.messages)
        for i in range(len(messages) - 1, -1, -1):
            m = messages[i]
            if isinstance(m, HumanMessage) or (isinstance(m, AIMessage) and not m.tool_calls):
                tagged = _tagged(m)
                if tagged is not None:
                    messages[i] = tagged
                    overrides["messages"] = messages
                break
        return request.override(**overrides) if overrides else request

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Any]) -> Any:
        return handler(self._apply(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[Any]]) -> Any:
        return await handler(self._apply(request))


def caching_middleware(model: BaseChatModel, settings) -> list[AgentMiddleware]:
    """The prompt-caching middleware appropriate for `model`, or none when caching is off or the
    model's provider has no explicit cache breakpoints (OpenAI-style providers cache automatically)."""
    if not getattr(settings, "prompt_caching", True):
        return []
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:  # pragma: no cover - langchain-anthropic is a hard dependency
        ChatAnthropic = None  # type: ignore[assignment]
    if ChatAnthropic is not None and isinstance(model, ChatAnthropic):
        return [AnthropicPromptCacheMiddleware(unsupported_model_behavior="ignore")]
    base_url = str(getattr(model, "openai_api_base", None) or "")
    model_name = str(getattr(model, "model_name", "") or "")
    if OPENROUTER_HOST in base_url and model_name.startswith("anthropic/"):
        return [OpenRouterPromptCacheMiddleware()]
    return []
