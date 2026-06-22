"""Request-scoped LLM token-usage accumulator.

case_review fulfils a single API request by running several LLM calls (Gemini
classifier/summariser + multiple Bedrock Converse pipeline stages). To report a
single ``token_usage`` block per response without threading a usage object
through every function signature, each LLM call records its usage into a
request-scoped accumulator and the route reads the running total before
returning.

Design notes
------------
* The accumulator is a **mutable dict** stored in a ``ContextVar``. Each FastAPI
  request runs in its own asyncio task → its own context, so the var is
  naturally request-scoped.
* Pipeline stages offload the blocking Bedrock SDK call via
  ``asyncio.to_thread``. ``to_thread`` copies the context, so the worker thread
  sees the *same dict object* — recording via **in-place mutation** (never
  ``.set()`` inside a thread) propagates back to the request. A lock guards
  concurrent stages.
* IMPORTANT: import this module under the single canonical path
  ``case_review.services.usage`` everywhere. The image puts both ``/app`` and
  ``/app/case_review`` on ``PYTHONPATH``; importing it as ``services.usage`` as
  well would create a *second* module instance with its own ContextVar and the
  totals would split.
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import Any

_usage_var: ContextVar[dict[str, int] | None] = ContextVar("cr_token_usage", default=None)
_lock = threading.Lock()


def _zero() -> dict[str, int]:
    # Internally track cache metrics but don't expose in API response.
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read_tokens": 0,  # Internal only, not in API response
        "cache_creation_tokens": 0,  # Internal only, not in API response
    }


def start_usage() -> None:
    """Begin a fresh accumulation for the current request. Call at route entry."""
    _usage_var.set(_zero())


def _add(input_tokens: int, output_tokens: int, cache_read: int, cache_creation: int) -> None:
    acc = _usage_var.get()
    if acc is None:
        # Not started (e.g. called outside a request) — nothing to accumulate into.
        return
    # In-place mutation so the change is visible across asyncio.to_thread copies.
    with _lock:
        acc["input_tokens"] += int(input_tokens or 0)
        acc["output_tokens"] += int(output_tokens or 0)
        acc["cache_read_tokens"] += int(cache_read or 0)
        acc["cache_creation_tokens"] += int(cache_creation or 0)
        # total = TRUE tokens processed. Bedrock reports inputTokens as the
        # UNCACHED remainder only; cacheRead + cacheWrite are separate fields for
        # tokens that were also part of the prompt. Summing all four gives the
        # real total the model processed (not the uncached slice, not a
        # cost-discounted number).
        acc["total_tokens"] = (
            acc["input_tokens"]
            + acc["output_tokens"]
            + acc["cache_read_tokens"]
            + acc["cache_creation_tokens"]
        )


def record_converse(response: dict[str, Any]) -> None:
    """Record token usage from a Bedrock Converse API response.

    Converse returns a ``usage`` block with camelCase keys:
    ``inputTokens``, ``outputTokens``, ``totalTokens`` and (when prompt caching
    is enabled) ``cacheReadInputTokens`` / ``cacheWriteInputTokens``.
    """
    usage = (response or {}).get("usage", {}) or {}
    _add(
        input_tokens=usage.get("inputTokens", 0),
        output_tokens=usage.get("outputTokens", 0),
        cache_read=usage.get("cacheReadInputTokens", 0),
        cache_creation=usage.get("cacheWriteInputTokens", 0),
    )


def record_and_print_converse(stage: str, response: dict[str, Any]) -> None:
    """Record token usage AND print a per-stage breakdown to stdout.

    Prints to stdout so Docker container logs capture the line.
    Format: [stage] in=N out=N cached=N (saved=N%) billed=N

    Bedrock billing with prompt caching:
      - Input tokens: full price
      - Output tokens: full price
      - Cache creation tokens: full price (one-time, on first request)
      - Cache read tokens: 10% of normal price (on cache hits)

    billed_total = inputTokens + outputTokens + cacheWriteInputTokens + (cacheReadInputTokens * 0.1)
    """
    usage = (response or {}).get("usage", {}) or {}
    inp = int(usage.get("inputTokens", 0) or 0)
    out = int(usage.get("outputTokens", 0) or 0)
    cached = int(usage.get("cacheReadInputTokens", 0) or 0)
    created = int(usage.get("cacheWriteInputTokens", 0) or 0)

    # Actual billed cost accounting for cache pricing
    billed = inp + out + created + int(cached * 0.1)

    _add(inp, out, cached, created)

    # Cache state: a read (hit) takes priority in the display, then a write
    # (cache built this call), then no caching at all. Checking `cached` first
    # (not `inp + cached`) is required — inp is always > 0, so an `inp + cached`
    # guard would shadow the cache-write branch on every call.
    if cached > 0:
        cache_pct = int(cached / (inp + cached) * 100)
        cache_str = f"cache_read={cached:,} ({cache_pct}% of input, saved ~{int(cached * 0.9):,})"
    elif created > 0:
        cache_str = f"cache_write={created:,}"
    else:
        cache_str = "no cache"

    print(
        f"[tokens/{stage:<12}] in={inp:>5,}  out={out:>4,}  {cache_str}  billed={billed:>6,}",
        flush=True,
    )


def record_gemini(response: Any) -> None:
    """Record token usage from a google-genai ``generate_content`` response.

    ``usage_metadata`` exposes ``prompt_token_count``, ``candidates_token_count``
    and ``cached_content_token_count`` (implicit caching, Gemini 2.5+).
    """
    um = getattr(response, "usage_metadata", None)
    _add(
        input_tokens=getattr(um, "prompt_token_count", 0) or 0,
        output_tokens=getattr(um, "candidates_token_count", 0) or 0,
        cache_read=getattr(um, "cached_content_token_count", 0) or 0,
        cache_creation=0,  # Gemini implicit caching has no separate creation cost
    )


def get_usage() -> dict[str, int]:
    """Snapshot the running total for the current request (API response format: 3 fields only).

    Cache metrics are tracked internally but NOT returned in API responses.
    """
    acc = _usage_var.get()
    if acc is None:
        acc = _zero()
    # Return only the 3 fields exposed in API responses
    return {
        "input_tokens": acc["input_tokens"],
        "output_tokens": acc["output_tokens"],
        "total_tokens": acc["total_tokens"],
    }


def get_usage_full() -> dict[str, int]:
    """Get full internal usage including cache metrics (for monitoring/analytics only)."""
    acc = _usage_var.get()
    return dict(acc) if acc is not None else _zero()


# ── Session-level cumulative tracking ────────────────────────────────────────
# Tracks total tokens across multiple requests in the same session.
_session_totals: ContextVar[dict[str, dict[str, int]] | None] = ContextVar("session_totals", default=None)


def start_session_tracking(session_id: str) -> None:
    """Initialize session token tracking. Call once per session."""
    totals = _session_totals.get() or {}
    if session_id not in totals:
        totals[session_id] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    _session_totals.set(totals)


def accumulate_to_session(session_id: str) -> None:
    """Add current request tokens to session total."""
    request_usage = get_usage()
    totals = _session_totals.get() or {}
    if session_id not in totals:
        totals[session_id] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    with _lock:
        totals[session_id]["input_tokens"] += request_usage["input_tokens"]
        totals[session_id]["output_tokens"] += request_usage["output_tokens"]
        totals[session_id]["total_tokens"] += request_usage["total_tokens"]
    _session_totals.set(totals)


def get_session_usage(session_id: str) -> dict[str, int]:
    """Get cumulative token usage for a session."""
    totals = _session_totals.get() or {}
    if session_id not in totals:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return dict(totals[session_id])
