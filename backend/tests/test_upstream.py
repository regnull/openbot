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


def _usage(prompt: int, cached: int) -> dict:
    return {"input_tokens": prompt, "output_tokens": 10, "total_tokens": prompt + 10,
            "input_token_details": {"cache_read": cached}}


async def test_an_upstream_that_keeps_missing_warm_calls_is_skipped_and_unpinned(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("openbot.runtime.upstream.time.monotonic", lambda: clock[0])
    pins = UpstreamPins(_fetch)
    await pins.record("bot1", "glm", "Z.AI")
    await pins.record("bot2", "glm", "Z.AI")
    pins.observe_cache("bot1", "glm", "z-ai", 20_000, 0)
    pins.observe_cache("bot1", "glm", "z-ai", 20_000, 0)
    pins.observe_cache("bot1", "glm", "z-ai", 20_000, 15_000)  # a hit resets the streak
    pins.observe_cache("bot1", "glm", "z-ai", 20_000, 700)
    pins.observe_cache("bot1", "glm", "z-ai", 20_000, 0)
    assert pins.ignored("glm") == [] and pins.pinned("bot1", "glm") == "z-ai"
    pins.observe_cache("bot1", "glm", "z-ai", 20_000, 0)
    assert pins.ignored("glm") == ["z-ai"]
    assert pins.pinned("bot1", "glm") is None and pins.pinned("bot2", "glm") is None
    assert pins.ignored("other-model") == []  # skips are per model
    clock[0] += 6 * 3600 + 1
    assert pins.ignored("glm") == []  # and lapse, so the upstream gets another chance


async def test_the_skip_list_is_capped_so_routing_never_runs_out(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("openbot.runtime.upstream.time.monotonic", lambda: clock[0])

    async def many(m):
        return {f"host {i}": f"host{i}" for i in range(20)}

    pins = UpstreamPins(many)
    await pins.slug_for("glm", "host 0")  # loads the endpoint list
    for i in range(12):
        clock[0] += 1
        for _ in range(3):
            pins.observe_cache("bot1", "glm", f"host{i}", 20_000, 0)
    skipped = pins.ignored("glm")
    assert len(skipped) == 10 and "host0" not in skipped and "host11" in skipped


async def test_the_middleware_moves_off_a_non_caching_upstream(settings):
    settings.openrouter_provider_order = []
    pins = UpstreamPins(_fetch)
    mw = StickyUpstreamMiddleware(pins, "bot1", "z-ai/glm-5.3-flash", settings)
    sent = []
    # Z.AI answers four calls without caching (the first is cold and not judged), then DeepInfra caches.
    served = iter([("Z.AI", 0)] * 4 + [("DeepInfra", 0), ("DeepInfra", 18_000)])

    async def handler(request):
        sent.append((request.model_settings.get("extra_body") or {}).get("provider"))
        name, cached = next(served)
        return AIMessage("ok", response_metadata={UPSTREAM_KEY: [name]}, usage_metadata=_usage(20_000, cached))

    for _ in range(6):
        await mw.awrap_model_call(_request(model()), handler)
    assert sent[0] is None
    assert sent[1] == sent[2] == sent[3] == {"order": ["z-ai"], "allow_fallbacks": True}
    assert sent[4] == {"ignore": ["z-ai"]}  # three warm misses: unpinned and skipped
    assert sent[5] == {"order": ["deepinfra"], "allow_fallbacks": True, "ignore": ["z-ai"]}
    assert pins.pinned("bot1", "z-ai/glm-5.3-flash") == "deepinfra"


async def test_calls_that_switched_upstream_are_cold_and_not_judged(settings):
    settings.openrouter_provider_order = []
    pins = UpstreamPins(_fetch)
    mw = StickyUpstreamMiddleware(pins, "bot1", "z-ai/glm-5.3-flash", settings)
    served = iter(["Z.AI", "DeepInfra"] * 4)

    async def handler(request):
        return AIMessage("ok", response_metadata={UPSTREAM_KEY: [next(served)]}, usage_metadata=_usage(20_000, 0))

    for _ in range(8):
        await mw.awrap_model_call(_request(model()), handler)
    assert pins.ignored("z-ai/glm-5.3-flash") == []


async def test_the_last_upstream_left_is_never_skipped():
    """An ignore list naming every upstream would fail every call to the model with "no endpoints"."""

    async def two(m):
        return {"z.ai": "z-ai", "deepinfra": "deepinfra"}

    pins = UpstreamPins(two)
    await pins.slug_for("glm", "Z.AI")
    for slug in ("z-ai", "deepinfra"):
        for _ in range(3):
            pins.observe_cache("bot1", "glm", slug, 20_000, 0)
    assert pins.ignored("glm") == ["z-ai"]  # deepinfra is all that is left, so it stays

    async def offline(m):
        raise OSError("down")

    blind = UpstreamPins(offline)
    await blind.slug_for("glm", "Z.AI")
    for _ in range(3):
        blind.observe_cache("bot1", "glm", "z-ai", 20_000, 0)
    assert blind.ignored("glm") == []  # without the endpoint list it cannot tell, so it skips nothing


async def test_warm_calls_are_judged_on_what_could_have_been_cached(settings):
    """A big tool result makes the next prompt much longer; only the previous call's part of it can be
    cached, so 8k cached of a 38k prompt that followed an 8k one is a full hit, not a miss."""
    settings.openrouter_provider_order = []
    pins = UpstreamPins(_fetch)
    mw = StickyUpstreamMiddleware(pins, "bot1", "z-ai/glm-5.3-flash", settings)
    # Each warm call has under 25% of its whole prompt cached, but all of the previous call's.
    calls = iter([(8_000, 0), (38_000, 8_000), (160_000, 38_000), (700_000, 160_000)])

    async def handler(request):
        prompt, cached = next(calls)
        return AIMessage("ok", response_metadata={UPSTREAM_KEY: ["Z.AI"]}, usage_metadata=_usage(prompt, cached))

    for _ in range(4):
        await mw.awrap_model_call(_request(model()), handler)
    assert pins.ignored("z-ai/glm-5.3-flash") == []


async def test_miss_streaks_are_per_bot():
    pins = UpstreamPins(_fetch)
    await pins.slug_for("glm", "Z.AI")
    for bot in ("bot1", "bot2", "bot3"):  # one ordinary miss each does not add up to a skip
        pins.observe_cache(bot, "glm", "z-ai", 20_000, 0)
    pins.observe_cache("bot1", "glm", "z-ai", 20_000, 0)
    pins.observe_cache("bot2", "glm", "z-ai", 20_000, 15_000)  # bot2's hit does not clear bot1's streak
    pins.observe_cache("bot1", "glm", "z-ai", 20_000, 0)
    assert pins.ignored("glm") == ["z-ai"]


async def test_a_pin_to_a_skipped_upstream_is_not_sent(settings):
    """A call in flight when its upstream was skipped re-pins the bot to it; the request must not then
    name the same upstream in both order and ignore."""
    settings.openrouter_provider_order = []
    pins = UpstreamPins(_fetch)
    await pins.slug_for("z-ai/glm-5.3-flash", "Z.AI")
    for _ in range(3):
        pins.observe_cache("bot2", "z-ai/glm-5.3-flash", "z-ai", 20_000, 0)
    await pins.record("bot1", "z-ai/glm-5.3-flash", "Z.AI")
    mw = StickyUpstreamMiddleware(pins, "bot1", "z-ai/glm-5.3-flash", settings)
    sent = []

    async def handler(request):
        sent.append(request.model_settings["extra_body"]["provider"])
        return AIMessage("ok")

    await mw.awrap_model_call(_request(model()), handler)
    assert sent == [{"ignore": ["z-ai"]}]
