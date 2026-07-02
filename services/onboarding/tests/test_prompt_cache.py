from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from voice.prompt_cache import cache_key_for, cache_stats, get_or_create_cache, reset_for_tests


@pytest.fixture(autouse=True)
def _clean_cache_state():
    reset_for_tests()
    yield
    reset_for_tests()


def _cache_result(cache_name: str) -> MagicMock:
    # NOTE: MagicMock(name=...) sets the mock's own repr name, NOT a `.name`
    # attribute on the object — must assign it after construction instead.
    result = MagicMock()
    result.name = cache_name
    return result


def _mock_client(cache_name: str = "cachedContents/abc123") -> MagicMock:
    client = MagicMock()
    client.aio.caches.create = AsyncMock(return_value=_cache_result(cache_name))
    return client


@pytest.mark.asyncio
async def test_creates_cache_on_first_call() -> None:
    client = _mock_client("cachedContents/first")
    name = await get_or_create_cache(client, "gemini-3.1-flash-live-preview", "static prompt A")
    assert name == "cachedContents/first"
    client.aio.caches.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_reuses_cache_for_identical_content() -> None:
    """The core cacheability guarantee — same content, same session count of
    API calls to create a new cache should be exactly one, not N."""
    client = _mock_client("cachedContents/reused")
    name1 = await get_or_create_cache(client, "model-x", "identical static prompt")
    name2 = await get_or_create_cache(client, "model-x", "identical static prompt")
    assert name1 == name2 == "cachedContents/reused"
    client.aio.caches.create.assert_awaited_once()  # NOT called twice


@pytest.mark.asyncio
async def test_creates_distinct_cache_for_different_content() -> None:
    client = _mock_client()
    client.aio.caches.create.side_effect = [
        _cache_result("cachedContents/one"),
        _cache_result("cachedContents/two"),
    ]
    name1 = await get_or_create_cache(client, "model-x", "prompt one")
    name2 = await get_or_create_cache(client, "model-x", "prompt two")
    assert name1 != name2
    assert client.aio.caches.create.await_count == 2


@pytest.mark.asyncio
async def test_falls_back_to_none_on_cache_creation_failure() -> None:
    """Callers MUST treat None as "use inline system_instruction" — this is
    the safety net if the API call fails for any reason (quota, network,
    genuinely unsupported model)."""
    client = MagicMock()
    client.aio.caches.create = AsyncMock(side_effect=RuntimeError("quota exceeded"))
    name = await get_or_create_cache(client, "model-x", "some prompt")
    assert name is None


@pytest.mark.asyncio
async def test_cache_stats_reflects_distinct_entries() -> None:
    client = _mock_client()
    client.aio.caches.create.side_effect = [
        _cache_result("cachedContents/one"),
        _cache_result("cachedContents/two"),
    ]
    assert cache_stats()["entries"] == 0
    await get_or_create_cache(client, "model-x", "prompt one")
    await get_or_create_cache(client, "model-x", "prompt two")
    assert cache_stats()["entries"] == 2


def test_cache_key_for_is_deterministic_and_short() -> None:
    key1 = cache_key_for("some static prompt content")
    key2 = cache_key_for("some static prompt content")
    key3 = cache_key_for("different content")
    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 12
