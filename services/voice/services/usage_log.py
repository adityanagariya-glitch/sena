"""Per-API token-usage logging for the voice service.

Prints a single line per LLM call to stdout (captured in Docker logs), in the
same shape used across the SENA AI services:

    [tokens/<stage>] in=<input> out=<output> <cache_info> total=<input+output>

Cache info is logged (e.g. "cache_read=X" or "cache_write=X") but NOT included
in the API response — the response keeps total=input+output only.
"""

from __future__ import annotations


def log_token_usage(
    stage: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> None:
    """Log per-stage token usage with optional cache metrics (logs only, not API)."""
    import sys
    inp = int(input_tokens or 0)
    out = int(output_tokens or 0)
    cached_read = int(cache_read_tokens or 0)
    cached_write = int(cache_write_tokens or 0)
    sys.stderr.write(f"[DEBUG] log_token_usage called: stage={stage} in={inp} out={out}\n")
    sys.stderr.flush()

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

    print(
        f"[tokens/{stage}] in={inp:,}  out={out:,}  {cache_str}  billed={billed:,}",
        flush=True,
    )
