"""Prompt caching: the right middleware per provider, correct breakpoints on the request, and the
direct-Anthropic routing that makes full caching possible for OpenRouter `anthropic/...` models."""
from langchain.agents.middleware import ModelRequest
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from openbot.config import Settings
from openbot.db.models import BotProfile
from openbot.runtime.caching import (
    CACHE_CONTROL,
    OpenRouterPromptCacheMiddleware,
    caching_middleware,
)
from openbot.runtime.providers import (
    chat_model,
    effective_bot_profile,
    openrouter_to_anthropic_model,
)


def s(**kw):
    return Settings(_env_file=None, **kw)


def openrouter(model="anthropic/claude-sonnet-5"):
    return ChatOpenAI(model=model, api_key="k", base_url="https://openrouter.ai/api/v1")


def request(messages, system="You are a bot."):
    return ModelRequest(model=openrouter(), messages=messages, system_message=SystemMessage(content=system),
                        tool_choice=None, tools=[], response_format=None, state={"messages": messages}, runtime=None,
                        model_settings={})


def test_middleware_selection_by_provider():
    st = s()
    assert isinstance(caching_middleware(ChatAnthropic(model="claude-sonnet-5", api_key="k"), st)[0], AnthropicPromptCachingMiddleware)
    assert isinstance(caching_middleware(openrouter(), st)[0], OpenRouterPromptCacheMiddleware)
    assert caching_middleware(openrouter("openai/gpt-5.5"), st) == []          # OpenAI caches automatically
    assert caching_middleware(ChatOpenAI(model="gpt-5.5", api_key="k"), st) == []
    assert caching_middleware(ChatAnthropic(model="claude-sonnet-5", api_key="k"), s(prompt_caching=False)) == []


def test_openrouter_middleware_tags_system_and_latest_human_message():
    msgs = [HumanMessage(content="[You]: please build it"),
            AIMessage(content="", tool_calls=[{"name": "list_files", "args": {}, "id": "c1", "type": "tool_call"}]),
            ToolMessage(content="a.py\nb.py", tool_call_id="c1")]
    out = OpenRouterPromptCacheMiddleware()._apply(request(msgs))
    assert out.system_message.content == [{"type": "text", "text": "You are a bot.", "cache_control": CACHE_CONTROL}]
    human = out.messages[0]
    assert human.content == [{"type": "text", "text": "[You]: please build it", "cache_control": CACHE_CONTROL}]
    # tool messages cannot carry the breakpoint through the OpenAI-compatible client, so they are left alone
    assert out.messages[2].content == "a.py\nb.py"
    # the original request objects are untouched
    assert msgs[0].content == "[You]: please build it"


def test_openrouter_middleware_skips_empty_text_and_keeps_other_blocks():
    msgs = [HumanMessage(content=[{"type": "text", "text": "hi"}, {"type": "text", "text": "  "}])]
    out = OpenRouterPromptCacheMiddleware()._apply(request(msgs, system=" "))
    # a blank system prompt gets no (invalid, empty) cache block
    assert out.system_message.content == " "
    assert out.messages[0].content == [{"type": "text", "text": "hi", "cache_control": CACHE_CONTROL}, {"type": "text", "text": "  "}]


def test_openrouter_anthropic_models_go_direct_when_key_present():
    st = s(openrouter_api_key="k", anthropic_api_key="a", bot_model="anthropic/claude-sonnet-5")
    bot = BotProfile(provider="auto", model="", model_settings={})
    assert effective_bot_profile(bot, st) == ("anthropic", "claude-sonnet-5")
    assert isinstance(chat_model(bot, st), ChatAnthropic)
    # explicit openrouter bots follow the same rule (the env model wins, as before)
    assert effective_bot_profile(BotProfile(provider="openrouter", model="x", model_settings={}), st) == ("anthropic", "claude-sonnet-5")
    # no Anthropic key: stays on OpenRouter
    assert effective_bot_profile(bot, s(openrouter_api_key="k", bot_model="anthropic/claude-sonnet-5")) == ("openrouter", "anthropic/claude-sonnet-5")
    # opt out
    assert effective_bot_profile(bot, s(openrouter_api_key="k", anthropic_api_key="a", bot_model="anthropic/claude-sonnet-5",
                                        direct_anthropic=False)) == ("openrouter", "anthropic/claude-sonnet-5")
    # non-Anthropic models are unaffected
    assert effective_bot_profile(bot, s(openrouter_api_key="k", anthropic_api_key="a", bot_model="openai/gpt-5.5")) == ("openrouter", "openai/gpt-5.5")


def test_openrouter_to_anthropic_model_ids():
    assert openrouter_to_anthropic_model("anthropic/claude-sonnet-5") == "claude-sonnet-5"
    assert openrouter_to_anthropic_model("anthropic/claude-opus-4.6") == "claude-opus-4-6"
    assert openrouter_to_anthropic_model("anthropic/claude-haiku-4.5") == "claude-haiku-4-5"
