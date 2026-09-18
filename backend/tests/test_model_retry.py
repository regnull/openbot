"""Model-call retries for transient upstream provider failures: classification, backoff, wiring
of the tunables, and the middleware loop (success, exhaustion, non-retryable, disabled)."""
import pytest

from openbot.config import Settings
from openbot.runtime.app_settings import TUNABLES, coerce
from openbot.runtime.retry import ModelRetryMiddleware, is_retryable


def s(**kw):
    return Settings(_env_file=None, **kw)


class ProviderError(Exception):
    """Mimics openai.APIStatusError / httpx errors carrying an HTTP status."""

    def __init__(self, status: int, message: str = "upstream error"):
        super().__init__(message)
        self.status_code = status


def request():
    from langchain.agents.middleware import ModelRequest
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    msgs = [HumanMessage(content="hi")]
    return ModelRequest(model=ChatOpenAI(model="m", api_key="k"), messages=msgs, system_message=None,
                        tool_choice=None, tools=[], response_format=None, state={"messages": msgs},
                        runtime=None, model_settings={})


def mw(**kw):
    defaults = {"max_attempts": 3, "base_delay": 0.001, "backoff_cap": 0.002}
    return ModelRetryMiddleware(**{**defaults, **kw})


async def run(m, calls):
    """Wrap a handler that appends to `calls` and pops scripted outcomes from the front."""
    outcomes = calls["outcomes"]

    async def handler(_request):
        calls["n"] += 1
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return await m.awrap_model_call(request(), handler)


async def test_retry_until_success():
    calls = {"n": 0, "outcomes": [ProviderError(502), ProviderError(429), "ok"]}
    assert await run(mw(), calls) == "ok"
    assert calls["n"] == 3


async def test_retries_exhausted_reraises_last_error():
    calls = {"n": 0, "outcomes": [ProviderError(502, "first"), ProviderError(502, "last")]}
    with pytest.raises(ProviderError, match="last"):
        await run(mw(max_attempts=2), calls)
    assert calls["n"] == 2


async def test_non_retryable_error_fails_immediately():
    calls = {"n": 0, "outcomes": [ProviderError(401, "invalid api key")]}
    with pytest.raises(ProviderError, match="invalid api key"):
        await run(mw(max_attempts=5), calls)
    assert calls["n"] == 1


async def test_max_attempts_zero_or_negative_disables_retries():
    for attempts in (0, -3):
        calls = {"n": 0, "outcomes": [ProviderError(502)]}
        with pytest.raises(ProviderError):
            await run(mw(max_attempts=attempts), calls)
        assert calls["n"] == 1


async def test_generic_upstream_message_pattern_is_retried_but_unknown_is_not():
    relace = Exception("Upstream error from Relace: The model stopped before completing the response.")
    calls = {"n": 0, "outcomes": [relace, "ok"]}
    assert await run(mw(), calls) == "ok"
    unknown = Exception("Upstream error from Somewhere: mysterious failure")
    calls = {"n": 0, "outcomes": [unknown]}
    with pytest.raises(Exception, match="mysterious"):
        await run(mw(), calls)
    assert calls["n"] == 1


def test_is_retryable_classification():
    for status in (408, 409, 425, 429, 500, 502, 503, 529):
        assert is_retryable(ProviderError(status)), status
    for status in (400, 401, 403, 404, 422):
        assert not is_retryable(ProviderError(status)), status
    assert not is_retryable(Exception("boom"))                       # unknown, no status: never retried
    assert is_retryable(Exception("The model stopped before completing the response."))


def test_backoff_delay_is_exponential_with_cap_and_jitter():
    m = mw(max_attempts=10, base_delay=2.0, backoff_cap=60.0)
    for attempt in range(1, 6):
        assert 0 <= m._delay(attempt) <= 2.0 * 2 ** (attempt - 1)
    assert m._delay(20) <= 60.0                                      # capped


def test_config_defaults_and_custom_values():
    st = s()
    assert (st.model_retry_max_attempts, st.model_retry_base_delay, st.model_retry_backoff_cap) == (3, 2.0, 60.0)
    st = s(model_retry_max_attempts=5, model_retry_base_delay=0.5, model_retry_backoff_cap=10.0)
    assert (st.model_retry_max_attempts, st.model_retry_base_delay, st.model_retry_backoff_cap) == (5, 0.5, 10.0)


def test_config_parses_env_values(monkeypatch):
    monkeypatch.setenv("MODEL_RETRY_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("MODEL_RETRY_BASE_DELAY", "1.5")
    monkeypatch.setenv("MODEL_RETRY_BACKOFF_CAP", "20")
    st = Settings(_env_file=None)
    assert (st.model_retry_max_attempts, st.model_retry_base_delay, st.model_retry_backoff_cap) == (4, 1.5, 20.0)


def test_tunables_registered_and_coerced():
    for key, kind, minimum in (("model_retry_max_attempts", "int", None),
                               ("model_retry_base_delay", "float", 0.0),
                               ("model_retry_backoff_cap", "float", 0.0)):
        assert key in TUNABLES
        from openbot.runtime.app_settings import field_type
        assert field_type(key) == kind
        assert coerce(key, 7 if kind == "int" else 2.5) == (7 if kind == "int" else 2.5)
        if minimum is not None:
            with pytest.raises(ValueError):
                coerce(key, -1)
    with pytest.raises(ValueError):
        coerce("model_retry_max_attempts", -1)
