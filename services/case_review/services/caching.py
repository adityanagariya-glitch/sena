"""Request-level caching for case note verdicts.

Cache key: SHA256(transcript) → full EvaluateResponse
TTL: 24 hours (cases shouldn't change within a day)
Max size: 10,000 entries (~10MB with typical responses)

Skips caching if the response contains errors or None values.
"""

import hashlib
import logging
from functools import wraps
from typing import Any, Callable

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# 24 hours in seconds; 10,000 transcript hashes
_verdict_cache: TTLCache[str, Any] = TTLCache(maxsize=10000, ttl=86400)


def _transcript_hash(transcript: str | None) -> str:
    """Create a stable cache key from transcript content."""
    if not transcript:
        return "empty"
    return hashlib.sha256(transcript.encode("utf-8")).hexdigest()


def cache_verdict(fn: Callable) -> Callable:
    """Decorator: cache the full EvaluateResponse by transcript.

    Skips caching if the result is falsy (None, error response, etc.).
    """

    @wraps(fn)
    async def wrapper(payload: Any, *args, **kwargs) -> Any:
        cache_key = _transcript_hash(payload.transcript if hasattr(payload, "transcript") else None)

        # Check cache hit
        if cache_key in _verdict_cache:
            logger.info("verdict_cache hit (transcript_hash=%s...)", cache_key[:12])
            return _verdict_cache[cache_key]

        # Cache miss: run the function
        result = await fn(payload, *args, **kwargs)

        # Store result if it's valid (not None, not error)
        if result and not getattr(result, "error", False):
            _verdict_cache[cache_key] = result
            logger.info("verdict_cache store (transcript_hash=%s... size=%d)", cache_key[:12], len(_verdict_cache))

        return result

    return wrapper


def clear_cache() -> None:
    """Clear all cached verdicts. Useful for testing."""
    _verdict_cache.clear()
