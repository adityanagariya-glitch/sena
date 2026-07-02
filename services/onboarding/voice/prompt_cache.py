"""Explicit Gemini cache for onboarding's static (step/mode) system prompt.

Background: gemini_live.py previously carried a comment claiming explicit
prompt caching (client.aio.caches.create) is unsupported for the Live API.
That's incorrect — voice/services/gemini_live_service.py in this same
codebase already does exactly this, successfully, on its own Gemini Live
session. The comment was never revisited after that was proven out.

Why this isn't a copy-paste of voice's cache: voice caches ONE fixed constant
string (identical for every session), so a single module-level cache serves
the whole service. Onboarding's static prompt varies by (step_id, mode,
voice_coverage, grounding) — prompt_builder.build_static_system_prompt()
produces a different string per combination. This module keeps one cache
entry PER DISTINCT static-prompt string (keyed by its content hash), not one
global cache. Hashing the actual content — rather than trying to enumerate
which inputs vary — means a cache key is always correct even if some future
change makes the static prompt vary in a way nobody anticipated here: same
content -> hit, anything different -> miss and a fresh cache entry, never a
wrong-content hit.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from google import genai

log = structlog.get_logger(__name__)

_CACHE_TTL_SEC = 86400  # 24h — matches voice's convention
_CACHE_RENEW_BEFORE_SEC = 1800  # renew when <30 min remain

# content_hash -> (cache_name, expires_at_monotonic)
_cache_entries: dict[str, tuple[str, float]] = {}
_cache_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


def _hash_prompt(static_prompt: str) -> str:
    return hashlib.sha256(static_prompt.encode("utf-8")).hexdigest()


def cache_key_for(static_prompt: str) -> str:
    """Expose the hash so callers can log/correlate without duplicating logic."""
    return _hash_prompt(static_prompt)[:12]


async def get_or_create_cache(
    client: "genai.Client", model: str, static_prompt: str
) -> str | None:
    """Return a Gemini cache name for this exact static-prompt content,
    creating or renewing it as needed.

    Returns None on ANY failure (including if the SDK/model genuinely
    doesn't support caching for this model) — callers MUST fall back to
    passing static_prompt as an inline system_instruction transparently, the
    same way voice's gemini_live_service.py does.
    """
    from google.genai import types  # local import: keep this module importable without the SDK installed

    key = _hash_prompt(static_prompt)
    async with _get_lock():
        now = time.monotonic()
        entry = _cache_entries.get(key)
        if entry and now < entry[1] - _CACHE_RENEW_BEFORE_SEC:
            return entry[0]
        try:
            cache = await client.aio.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    contents=[types.Content(
                        role="user",
                        parts=[types.Part(text=static_prompt)],
                    )],
                    ttl=f"{_CACHE_TTL_SEC}s",
                ),
            )
            _cache_entries[key] = (cache.name, now + _CACHE_TTL_SEC)
            log.info(
                "onboarding_prompt_cache_created",
                cache_key=key[:12],
                cache_name=cache.name,
                model=model,
                ttl_sec=_CACHE_TTL_SEC,
                prompt_chars=len(static_prompt),
            )
            return cache.name
        except Exception:
            log.warning(
                "onboarding_prompt_cache_failed_fallback_inline",
                cache_key=key[:12],
                model=model,
            )
            return None


def cache_stats() -> dict:
    """Diagnostic: how many distinct static-prompt variants are cached right
    now. Useful to sanity-check the (step, mode, voice_coverage, grounding)
    combination count actually seen in production stays small."""
    return {"entries": len(_cache_entries)}


def reset_for_tests() -> None:
    """Test-only: clear module-level cache state between test cases."""
    global _cache_lock
    _cache_entries.clear()
    _cache_lock = None
