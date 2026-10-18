"""Context-window limits derived from the model catalog, and context-overflow errors.

OpenBot's summarize/clear thresholds were fixed token counts (`summary_trigger_tokens` etc. in
`openbot/config.py`), the same for a 200k-token model and an 8k one: a small-context model
overflowed before any threshold fired, and a large-context one summarized (and dropped tool
results) long before it had to. The model catalog (`openbot/runtime/model_catalog.py`) already
knows every model's context window; these functions derive the thresholds from it.

Precedence (issue #249):
1. An explicit runtime override of `summary_trigger_tokens` / `context_trigger_tokens`
   (`openbot/runtime/app_settings.py` TUNABLES) wins — user intent beats derivation.
2. Derived from the model's known context window (OpenCode's compaction formula, MIT licensed,
   https://github.com/anomalyco/opencode): the usable window is what remains after reserving the
   model's output limit, never eating more of the window than `RESERVE_SHARE` of it; the trigger
   then sits at `TRIGGER_SHARE` of that usable window.
3. The built-in defaults (60k summarize / 40k clear) as the fallback for a model the catalog has
   never heard of — deliberately conservative; OpenCode assumes 200k for unknown models, we do
   not adopt that.

`is_context_overflow` recognizes the "prompt is too long" family across providers — OpenAI
`context_length_exceeded`, Anthropic "prompt is too long", Gemini "exceeds the maximum context
length", OpenRouter's pass-throughs — by message pattern, so it works no matter which SDK class
carries the error. `ModelRetryMiddleware` uses it to summarize the conversation and retry the
same call once instead of failing the run.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# OpenCode compaction thresholds (MIT licensed, https://github.com/anomalyco/opencode): compaction
# fires when the context reaches the window minus a reserve for the model's reply. The reserve is
# max(10% of the window, the model's output limit, 16k), so a small window keeps room to answer
# and a large one is not eaten by the reserve. The trigger then sits at 70% of the usable window:
# the same sizing as upstream's forced summarize on overflow (OpenCode PR #31005).
TRIGGER_SHARE = 0.7
# Assumed output limit when the catalog knows a window but no output limit (OpenCode RESERVE_MIN).
RESERVE_MIN = 16_000
# Share of the window the reserve grows with, until it reaches RESERVE_MIN (OpenCode: the reserve
# is max(10% of window, 16k) once the window is at least 2x 16k).
RESERVE_SHARE = 0.1
# Tokens held back from a derived trigger, after the output reserve, as a safety margin for the
# catalog's count being optimistic and the local token estimate being rough.
SAFETY_MARGIN_TOKENS = 4_000
# Most of a reply the reserve holds room for (OpenCode OUTPUT_TOKEN_MAX). Catalogs report some
# models' output limit as nearly the whole window (GLM-5.3-Flash: 943,717 of 1,048,576), and
# reserving all of it summarized a 1M-token model at ~70k (2026-10-17). A bot's reply never needs more.
OUTPUT_TOKEN_MAX = 32_000
# Ceiling on a derived summary trigger. Every call re-sends the whole context, so a 1M window
# summarizing at ~700k made each call slow and costly; past this a summary is cheaper than
# carrying the history. At 200k (2026-10-17) a 1M-window bot cleared nothing until ~133k of
# messages and its calls passed 170k tokens; 100k keeps clearing near 67k, above the ~47k that
# made bots re-read what had just been cleared. An explicit `summary_trigger_tokens` override
# may still go higher.
MAX_DERIVED_SUMMARY_TRIGGER = 100_000

# Built-in fallbacks (the old fixed defaults), used when the window is unknown or a trigger
# setting is None without a window to derive from.
FALLBACK_SUMMARY_TRIGGER = 60_000
FALLBACK_CLEAR_TRIGGER = 40_000
# A derived clear trigger sits at this share of the derived summary trigger, the fallbacks' 40k:60k:
# cheap clearing of old tool results fires turns before the costlier summary, never on the same turn
# (one turn tripping both made a bot re-read everything it had just lost, 2026-09-17).
CLEAR_SHARE = FALLBACK_CLEAR_TRIGGER / FALLBACK_SUMMARY_TRIGGER

OVERFLOW_PATTERNS: tuple[str, ...] = (
    "prompt is too long",  # Anthropic (400)
    "context_length_reached",  # OpenAI Chat/Responses API (400)
    "context_length_exceeded",  # OpenAI-compatible providers (OpenRouter, LiteLLM, vLLM)
    "exceeds the maximum context length",  # Gemini
    "request too large",  # OpenRouter / upstream proxies
    "input length and `max_tokens` exceed context limit",  # OpenAI Responses API
    "reduce the length of the messages",  # various OpenAI-compatible providers
    "too many tokens",  # OpenRouter pass-throughs, e.g. Mistral
    "maximum context length",  # llama.cpp, Ollama, other local runtimes
    "context window is full",
    "exceed the context window",
    "exceeds the model's maximum context",
    "input is too long",
)

# Compiled once; matched against the lowercased error string.
_OVERFLOW_RE = re.compile("|".join(re.escape(p) for p in OVERFLOW_PATTERNS))


async def model_context_limits(
    provider: str,
    model: str,
    catalog: Any,
) -> tuple[int | None, int | None]:
    """The model's (context window, output limit) from the cached catalog, or (None, None).

    `catalog` is the `ModelCatalog` service (or None in tests); `await catalog.get(provider)` is
    served from the in-memory cache after startup, so this stays cheap per run. A catalog miss
    (model typed by hand, provider without a catalog entry) returns (None, None) and callers fall
    back to the built-in default triggers. Any catalog failure is logged and treated as unknown.
    """
    get = getattr(catalog, "get", None) if catalog is not None else None
    if get is None:
        return None, None
    try:
        result = await get(provider)
    except Exception:
        log.debug("model catalog lookup failed for %s/%s", provider, model, exc_info=True)
        return None, None
    for entry in getattr(result, "models", None) or []:
        if entry.get("id") != model:
            continue
        raw_window, raw_output = entry.get("context"), entry.get("output")
        try:
            window = int(raw_window) if raw_window is not None else 0
        except (TypeError, ValueError):
            window = 0
        try:
            output = int(raw_output) if raw_output is not None else None
        except (TypeError, ValueError):
            output = None
        return window or None, output
    return None, None


def derive_trigger_thresholds(
    window: int | None,
    *,
    summary_trigger: int | None,
    clear_trigger: int | None,
    output_limit: int | None = None,
    fixed_tokens: int = 0,
) -> tuple[int, int]:
    """Summarize/clear thresholds for a model with context window `window` (None = unknown).

    `summary_trigger`/`clear_trigger` are the runtime values of the two settings: None means
    "derive from the window", a number means "explicit override — user intent wins". Unknown
    window and None both fall back to the built-in defaults, which keeps today's behavior for
    hand-typed models. Known window: OpenCode's compaction formula — reserve = max(10% of the
    window, the model's output limit up to `OUTPUT_TOKEN_MAX`, 16k), capped at half the window so a
    tiny window keeps room for the conversation at all; usable = window - reserve; summary trigger =
    70% of usable, no higher than `MAX_DERIVED_SUMMARY_TRIGGER`, and the clear trigger
    `CLEAR_SHARE` of that, so clearing still fires first. `window <= 0`
    counts as unknown (the catalog reports unknown windows as 0).

    `fixed_tokens` is what every call sends besides the run's messages (the system prompt). The
    triggers count only messages, so it comes out of the usable window: a ~50k system prompt
    under a 200k window otherwise left a summary trigger plus a full reply past the window.
    """
    summary = max(1, int(summary_trigger)) if summary_trigger is not None else None
    clear = max(1, int(clear_trigger)) if clear_trigger is not None else None
    if not window or window <= 0:
        return (
            summary if summary is not None else FALLBACK_SUMMARY_TRIGGER,
            clear if clear is not None else FALLBACK_CLEAR_TRIGGER,
        )
    reserve = max(RESERVE_MIN, min(output_limit or 0, OUTPUT_TOKEN_MAX))
    if RESERVE_SHARE * window <= RESERVE_MIN:
        # A window under 2x the minimum reserve: cap the reserve at half the window, so the
        # conversation keeps at least half of it (OpenCode's 2x RESERVE_MIN gate).
        reserve = min(reserve, window // 2)
    # The margin shrinks with a small window: a fixed 4k on top of a halved 8k window left 1 token.
    margin = min(SAFETY_MARGIN_TOKENS, int(window * RESERVE_SHARE))
    usable = max(1, window - reserve - margin - max(0, fixed_tokens))
    derived = max(1, min(int(usable * TRIGGER_SHARE), MAX_DERIVED_SUMMARY_TRIGGER))
    return (
        summary if summary is not None else derived,
        clear if clear is not None else max(1, int(derived * CLEAR_SHARE)),
    )


def is_context_overflow(err: BaseException) -> bool:
    """True when a provider error says the request does not fit the model's context window.

    Matched on the error's text because the same condition arrives as many SDK types: OpenAI's
    `BadRequestError` with `code: "context_length_exceeded"`, Anthropic's `BadRequestError`
    ("prompt is too long: N tokens > M maximum"), Gemini's `InvalidArgument`, and OpenRouter's
    pass-through of whichever of those its upstream raised. A 400 alone proves nothing (most
    400s are permanent failures with no recovery), so the message decides.
    """
    message = str(err).lower()
    return bool(message) and _OVERFLOW_RE.search(message) is not None
