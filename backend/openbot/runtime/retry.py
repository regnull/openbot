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

Classification: only errors the providers expose as HTTP with a transient status (408/409/425/
429/5xx), plus LangChain's `ModelHTTPError`, are retried; auth, permission and invalid-request
failures (400/401/403/404/422) fail immediately. Some upstream failures (like the Relace one
above) surface as a generic `APIError` without a status code; those are matched by the known
message pattern "model stopped before completing" — the limitation is that a *generic* provider
error without a status code and without a recognizable message is not retried, by design (it
could be permanent).
"""
from __future__ import annotations

import asyncio
import logging
import random

from langchain.agents.middleware import AgentMiddleware, ModelRequest

log = logging.getLogger(__name__)

# HTTP statuses worth a second try (rate limit, upstream hiccup, transient conflict, timeout).
RETRYABLE_STATUS = {408, 409, 425, 429, *range(500, 600)}

# Generic APIError bodies seen from upstream model providers without an HTTP status attached.
UPSTREAM_MESSAGE_PATTERNS = ("model stopped before completing",)


def _error_status(err: Exception) -> int | None:
    """Best-effort HTTP status of a provider error, or None when the error carries none."""
    for attr in ("status_code", "_status_code", "code", "http_status"):
        value = getattr(err, attr, None)
        if isinstance(value, int) and value > 0:
            return value
    return None


def is_retryable(err: Exception) -> bool:
    """True when `err` looks like a transient upstream model-provider failure.

    Retries what the provider marked transient (429/5xx/timeout via `openai.APIStatusError` or
    LangChain's `ModelHTTPError`) plus the known generic-upstream message pattern; never retries
    auth, permission or invalid-request errors."""
    status = _error_status(err)
    if status is not None:
        return status in RETRYABLE_STATUS
    # Some upstream failures surface as a bare APIError with no status code; retry only the
    # known transient pattern, never a generic provider error we cannot classify.
    message = str(err).lower()
    return any(pattern in message for pattern in UPSTREAM_MESSAGE_PATTERNS)


class ModelRetryMiddleware(AgentMiddleware):
    """Re-issue a model call that failed with a transient upstream provider error."""

    def __init__(self, max_attempts: int, base_delay: float, backoff_cap: float) -> None:
        self.max_attempts = max(1, max_attempts)  # <1 means "no retries": exactly one attempt
        self.base_delay = base_delay
        self.backoff_cap = backoff_cap

    def _delay(self, attempt: int) -> float:
        """Exponential backoff with a cap and full jitter (attempt is 1-based, the delay before it)."""
        return min(self.base_delay * 2 ** (attempt - 1), self.backoff_cap) * random.uniform(0.0, 1.0)

    def wrap_model_call(self, request: ModelRequest, handler):
        """Synchronous model calls are not retried (runs use `astream`); pass through."""
        return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler):
        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await handler(request)
            except Exception as err:
                if not is_retryable(err) or attempt >= self.max_attempts:
                    raise
                last = err
                delay = self._delay(attempt)
                log.warning("transient model error on attempt %d/%d: %s: %s — retrying in %.1fs",
                            attempt, self.max_attempts, type(err).__name__, err, delay)
                await asyncio.sleep(delay)
        raise last  # pragma: no cover - the loop always returns or raises
