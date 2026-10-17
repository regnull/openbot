"""Automatic retries for transient upstream model-provider failures.

A provider hiccup ("Upstream error from Relace: The model stopped before completing the
response.", an OpenRouter 502, an OpenAI 5xx) used to abort a whole bot run, leaving a human
to type "continue" to recover. `ModelRetryMiddleware` wraps every model call of an agent loop
(`awrap_model_call`) and re-issues a model call that failed with a transient upstream error,
so the run rides out a bad turn without dropping the request that triggered it.

Retry behavior is configurable through the same layered settings as everything else
(`Settings` in `openbot/config.py`, overridable at runtime via `TUNABLES` in
`openbot/runtime/app_settings.py`):

- `model_retry_max_attempts` (default 3; 0 or 1 disables retries entirely).
- `model_retry_base_delay` (default 2.0s): delay before the first retry.
- `model_retry_backoff_cap` (default 60s): maximum delay before any retry.

Delay for attempt N is `min(base * 2^(N-1), cap) + uniform(0, jitter)` — exponential with a cap
and full jitter, so concurrent runs desynchronize. When retries are exhausted the last error is
re-raised unchanged, so the run fails with the provider's own error message.

Classification: errors the providers expose as HTTP with a transient status (408/409/425/
429/5xx), plus LangChain's `ModelHTTPError`, and request timeouts (the SDKs' `APITimeoutError`
and httpx's `TimeoutException`, which carry no status; see `model_call_timeout`) and dropped connections (the SDKs'
`APIConnectionError`, and the raw httpx/httpx2 transport errors a reset mid-stream raises) are retried; auth, permission and invalid-request
failures (400/401/403/404/422) fail immediately. Some upstream failures (like the Relace one
above) surface as a generic `APIError` without a status code; those are matched by the known
message pattern "model stopped before completing" — the limitation is that a *generic* provider
error without a status code and without a recognizable message is not retried, by design (it
could be permanent).

Context overflow ("prompt is too long", "context_length_exceeded", ...) is neither transient
nor hopeless: the same call retried after compacting the conversation succeeds. See
`openbot/runtime/context_limits.py` for how an overflow is recognized. `ModelRetryMiddleware`
takes an optional `on_overflow` callback (the runner passes one that summarizes with the run's
own summarization middleware and hands back a shrunken `ModelRequest`); when a call fails with
a context overflow and the callback can shrink the request, the call is retried immediately
with the smaller request — once, so a summarizer that cannot shrink far enough fails fast
instead of looping. No callback (or one that returns None) leaves today's behavior: the run
fails with the provider's error. A second overflow after the summarizing retry is terminal:
one of the two impossible calls (the new one cannot summarize, the summary call itself cannot
fit) has failed, and retrying only delays the failure.
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time
from collections.abc import Awaitable, Callable

import anthropic
import httpx
import httpx2
import openai
from langchain.agents.middleware import AgentMiddleware, ModelRequest

from openbot.runtime.context_limits import is_context_overflow

log = logging.getLogger(__name__)

# HTTP statuses worth a second try (rate limit, upstream hiccup, transient conflict, timeout).
RETRYABLE_STATUS = {408, 409, 425, 429, 529, *range(500, 600)}

# Generic APIError bodies seen from upstream model providers without an HTTP status attached.
UPSTREAM_MESSAGE_PATTERNS = (
    "model stopped before completing",
    "econnreset",
    "socket hang up",
    "overloaded",
    "resource_exhausted",
)
# A call that hit model_call_timeout or lost its connection: no HTTP status, but as transient as a 5xx.
# The openai and anthropic SDKs use httpx2, whose exceptions are not httpx's; a connection reset while
# streaming reaches us as a raw httpx2.ReadError / RemoteProtocolError, not wrapped by the SDK.
TRANSIENT_ERRORS = (
    openai.APIConnectionError,
    anthropic.APIConnectionError,  # includes their APITimeoutError
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    httpx2.TimeoutException,
    httpx2.NetworkError,
    httpx2.RemoteProtocolError,
)


def _error_status(err: Exception) -> int | None:
    """Best-effort HTTP status of a provider error, or None when the error carries none."""
    for attr in ("status_code", "_status_code", "code", "http_status"):
        value = getattr(err, attr, None)
        if isinstance(value, int) and value > 0:
            return value
    return None


def is_retryable(err: Exception) -> bool:
    """True when `err` looks like a transient upstream model-provider failure.

    Retries what the provider marked transient (429/5xx via `openai.APIStatusError` or LangChain's
    `ModelHTTPError`), request timeouts, dropped connections, and the known generic-upstream message pattern; never retries
    auth, permission or invalid-request errors."""
    if isinstance(err, TRANSIENT_ERRORS):
        return True
    status = _error_status(err)
    if status is not None:
        return status in RETRYABLE_STATUS
    # Some upstream failures surface as a bare APIError with no status code; retry only the
    # known transient pattern, never a generic provider error we cannot classify.
    message = str(err).lower()
    return any(pattern in message for pattern in UPSTREAM_MESSAGE_PATTERNS)


def _response_headers(err: Exception):
    response = getattr(err, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if headers is None:
        headers = getattr(err, "headers", None)
    return headers


def _retry_after(err: Exception, cap: float) -> float | None:
    """Return a bounded server-requested retry delay, following OpenCode's retry policy."""
    # Adapted from OpenCode's session/retry.ts (MIT licensed).
    headers = _response_headers(err)
    if not headers:
        return None

    def get(name: str):
        try:
            return headers.get(name)
        except AttributeError:
            return None

    value = get("retry-after-ms")
    if value is not None:
        try:
            return min(max(float(value) / 1000, 0.0), cap)
        except (TypeError, ValueError):
            pass

    value = get("retry-after")
    if value is None:
        return None
    try:
        delay = max(float(value), 0.0)
    except (TypeError, ValueError):
        try:
            retry_at = email.utils.parsedate_to_datetime(value).timestamp()
        except (TypeError, ValueError, OverflowError):
            return None
        delay = max(retry_at - time.time(), 0.0)
    return min(delay, cap)


class ModelRetryMiddleware(AgentMiddleware):
    """Re-issue a model call that failed with a transient upstream provider error.

    With an `on_overflow` callback, a model call that failed with a context-overflow error is
    instead retried once on the request the callback returns (the runner's summarizer): see the
    module docstring. A second overflow on the summarized request fails the call — the run ends
    with the provider's error instead of looping.
    """

    def __init__(
        self,
        max_attempts: int,
        base_delay: float,
        backoff_cap: float,
        on_overflow: Callable[[ModelRequest], Awaitable[ModelRequest | None]] | None = None,
    ) -> None:
        self.max_attempts = max(1, max_attempts)  # <1 means "no retries": exactly one attempt
        self.base_delay = base_delay
        self.backoff_cap = backoff_cap
        self.on_overflow = on_overflow

    def _delay(self, attempt: int) -> float:
        """Exponential backoff with a cap and full jitter (attempt is 1-based, the delay before it)."""
        return min(self.base_delay * 2 ** (attempt - 1), self.backoff_cap) * random.uniform(
            0.0, 1.0
        )

    def wrap_model_call(self, request: ModelRequest, handler):
        """Synchronous model calls are not retried (runs use `astream`); pass through."""
        return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler):
        """Retry transient failures; on context overflow, summarize once and retry.

        `shrunk` is set once the `on_overflow` summarizer has produced a compacted request. The
        retry on it happens immediately (no backoff sleep) and does not consume a transient-retry
        attempt: a run that has been riding out 429s all day still gets its summarizing retry.
        A second overflow — with `shrunk` already set — is terminal: raise, don't loop.
        """
        shrunk: ModelRequest | None = None
        attempt = 0
        while True:
            use = shrunk if shrunk is not None else request
            attempt += 1
            try:
                return await handler(use)
            except Exception as err:
                if is_context_overflow(err):
                    if self.on_overflow is None:
                        raise
                    if shrunk is not None:
                        # Already summarized for this call; summarizing again cannot help — the
                        # summarizer produced this request and it still overflows.
                        raise
                    shrunk = await self.on_overflow(request)
                    if shrunk is None:
                        raise
                    log.info("context overflow: summarizing and retrying once")
                    # Not a transient-retry attempt: do not sleep, do not count it.
                    attempt -= 1
                    continue
                if not is_retryable(err) or attempt >= self.max_attempts:
                    raise
                server_delay = _retry_after(err, self.backoff_cap)
                delay = self._delay(attempt) if server_delay is None else server_delay
                log.warning(
                    "transient model error on attempt %d/%d: %s: %s — retrying in %.1fs",
                    attempt,
                    self.max_attempts,
                    type(err).__name__,
                    err,
                    delay,
                )
                await asyncio.sleep(delay)
