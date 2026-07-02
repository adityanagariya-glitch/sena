"""Per-API token-usage logging for the voice service.

Emits a single structured log line per LLM call, in the same shape used
across the SENA AI services:

    [tokens/<stage>] in=<input> out=<output> <cache_info> billed=<billed>

Cache info is logged (e.g. "cache_read=X") but NOT included in the API
response — the response keeps total=input+output only.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("sena.tokens")


def log_token_usage(
    stage: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> None:
    """Log per-stage token usage with optional cache metrics (logs only, not API)."""
    inp = int(input_tokens or 0)
    out = int(output_tokens or 0)
    cached_read = int(cache_read_tokens or 0)
    cached_write = int(cache_write_tokens or 0)

    # Cache state: read (hit) takes priority, then write, then no cache
    if cached_read > 0:
        cache_pct = int(cached_read / (inp + cached_read) * 100)
        cache_str = f"cache_read={cached_read:,} ({cache_pct}% of input, saved ~{int(cached_read * 0.9):,})"
    elif cached_write > 0:
        cache_str = f"cache_write={cached_write:,}"
    else:
        cache_str = "no cache"

    # Billed cost: input + output + cache_write + (cache_read * 0.1)
    billed = inp + out + cached_write + int(cached_read * 0.1)

    _log.info(
        "[tokens/%s] in=%s  out=%s  %s  billed=%s",
        stage, f"{inp:,}", f"{out:,}", cache_str, f"{billed:,}",
    )
    
    cache_str_stdout = ""
    if cached_read > 0 or cached_write > 0:
        cache_str_stdout = f" cache_read={cached_read:,} cache_write={cached_write:,}"

    print(
        f"[tokens/{stage}] input={inp:,} output={out:,}{cache_str_stdout} billed={billed:,}",
        flush=True,
    )
