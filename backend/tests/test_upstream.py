"""Sticky OpenRouter upstreams: record which upstream answered, pin the bot's next call to it."""

from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, AIMessageChunk

from openbot.runtime.providers import provider_chat_model
from openbot.runtime.upstream import (
    UPSTREAM_KEY,
    OpenRouterChatOpenAI,
    StickyUpstreamMiddleware,
    UpstreamPins,
    guess_slug,
    upstream_of,
)


def model(**kwargs) -> OpenRouterChatOpenAI:
    return OpenRouterChatOpenAI(model="z-ai/glm-5.3-flash", api_key="k", base_url="https://openrouter.ai/api/v1", **kwargs)


def test_streamed_replies_record_the_upstream_once_closing_chunks_arrive():
    m = model()
    chunks = [
        {"provider": "DeepInfra", "model": "z-ai/glm-5.3-flash", "choices": [{"index": 0, "delta": {"content": "hi"}}]},
        {"provider": "DeepInfra", "model": "z-ai/glm-5.3-flash", "choices": [{"index": 0, "delta": {"content": "!"}, "finish_reason": "stop"}]},
        {"provider": "DeepInfra", "choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
    ]
    gens = [m._convert_chunk_to_generation_chunk(c, AIMessageChunk, {}) for c in chunks]
    assert UPSTREAM_KEY not in gens[0].message.response_metadata  # not tagged on every token
    merged = gens[0].message + gens[1].message + gens[2].message
    assert merged.content == "hi!"
    assert upstream_of(merged) == "DeepInfra"  # survives chunk merging, which doubles strings


def test_non_streamed_replies_record_the_upstream():
    result = model()._create_chat_result(
        {
            "id": "x",
            "provider": "Z.AI",
            "model": "z-ai/glm-5.3-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    assert upstream_of(result.generations[0].message) == "Z.AI"


def test_openrouter_bots_get_the_recording_model(settings):
    settings.openrouter_api_key = "k"
    assert isinstance(provider_chat_model("openrouter", "z-ai/glm-5.3-flash", settings, None), OpenRouterChatOpenAI)


async def test_names_map_to_slugs_from_the_endpoint_list_with_a_guess_as_fallback(monkeypatch):
    # A machine minutes after boot: monotonic time is small, which once made "never fetched" look fresh.
    monkeypatch.setattr("openbot.runtime.upstream.time.monotonic", lambda: 5.0)
    fetches = []

    async def fetch(m):
        fetches.append(m)
        return {"z.ai": "z-ai", "inferencenet": "inference-net"}

    pins = UpstreamPins(fetch)
    assert await pins.slug_for("glm", "Z.AI") == "z-ai"
    assert await pins.slug_for("glm", "InferenceNet") == "inference-net"  # a guess would say "inferencenet"
    assert await pins.slug_for("glm", "Brand New Host") == "brand-new-host"
    assert fetches == ["glm"]  # cached

    async def broken(m):
        raise OSError("offline")

    assert await UpstreamPins(broken).slug_for("glm", "Z.AI") == guess_slug("Z.AI") == "z-ai"


def _request(m, settings=None) -> ModelRequest:
    return ModelRequest(model=m, messages=[], system_message=None, tool_choice=None, tools=[],
                        response_format=None, state={}, runtime=None, model_settings=settings or {})


async def _fetch(m):
    return {"z.ai": "z-ai", "deepinfra": "deepinfra"}


async def test_the_next_call_is_pinned_to_the_last_upstream_and_follows_a_fallback(settings):
    settings.openrouter_provider_order = []
    pins = UpstreamPins(_fetch)
    mw = StickyUpstreamMiddleware(pins, "bot1", "z-ai/glm-5.3-flash", settings)
    m = model(extra_body={"plugins": [{"id": "web"}]})
    sent, served = [], iter(["Z.AI", "Z.AI", "DeepInfra"])

    async def handler(request):
        sent.append(request.model_settings.get("extra_body"))
        return AIMessage("ok", response_metadata={UPSTREAM_KEY: [next(served)]})

    for _ in range(3):
        await mw.awrap_model_call(_request(m), handler)
    assert sent[0] is None  # nothing known yet: OpenRouter picks
    assert sent[1] == {"plugins": [{"id": "web"}], "provider": {"order": ["z-ai"], "allow_fallbacks": True}}
    assert sent[2]["provider"]["order"] == ["z-ai"]
    # Z.AI failed over to DeepInfra on the third call; the pin follows.
    assert pins.pinned("bot1", "z-ai/glm-5.3-flash") == "deepinfra"
    assert pins.pinned("bot2", "z-ai/glm-5.3-flash") is None  # pins are per bot


async def test_an_explicit_provider_order_wins(settings):
    settings.openrouter_provider_order = ["novita"]
    pins = UpstreamPins(_fetch)
    await pins.record("bot1", "z-ai/glm-5.3-flash", "Z.AI")
    mw = StickyUpstreamMiddleware(pins, "bot1", "z-ai/glm-5.3-flash", settings)
    sent = []

    async def handler(request):
        sent.append(request.model_settings.get("extra_body"))
        return AIMessage("ok", response_metadata={UPSTREAM_KEY: ["DeepInfra"]})

    await mw.awrap_model_call(_request(model()), handler)
    assert sent == [None]  # the model's own extra_body (the explicit order) is left alone
    assert pins.pinned("bot1", "z-ai/glm-5.3-flash") == "z-ai"  # and replies do not move the pin
