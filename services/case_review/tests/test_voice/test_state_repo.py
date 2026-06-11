"""Tests for VoiceStateRepo — uses fakeredis for isolation."""
from __future__ import annotations

import pytest
import pytest_asyncio

try:
    import fakeredis.aioredis as fakeredis_aio
    _HAS_FAKEREDIS = True
except ImportError:
    _HAS_FAKEREDIS = False

from voice.schema import build_case_note_schema
from voice.session_bootstrap import SessionBootstrap
from voice.state import CaseNoteVoiceState
from voice.state_repo import VoiceStateRepo

pytestmark = pytest.mark.skipif(not _HAS_FAKEREDIS, reason="fakeredis not installed")


@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def repo(fake_redis):
    return VoiceStateRepo(fake_redis)


def _make_state(session_id: str = "s-1") -> CaseNoteVoiceState:
    return CaseNoteVoiceState(
        session_id=session_id,
        case_note_id="cn-1",
        worker_id="w-1",
        client_id="liam-1",
        tenant_id="t-1",
    )


@pytest.mark.asyncio
async def test_state_roundtrip(repo) -> None:
    state = _make_state()
    schema = build_case_note_schema()
    await repo.create_session(state, schema, ttl_sec=600)
    loaded = await repo.get_state("s-1")
    assert loaded is not None
    assert loaded.session_id == "s-1"
    assert loaded.worker_id == "w-1"


@pytest.mark.asyncio
async def test_assert_session_owner_rejects_cross_tenant(repo) -> None:
    from fastapi import HTTPException

    state = _make_state()
    schema = build_case_note_schema()
    await repo.create_session(state, schema, ttl_sec=600)
    with pytest.raises(HTTPException) as exc_info:
        await repo.assert_session_owner("s-1", tenant_id="t-OTHER", worker_id="w-1")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_redis_keys_use_rp_voice_prefix(fake_redis, repo) -> None:
    """All keys must start with sena:rp_voice: — guards against onboarding-prefix bleed."""
    state = _make_state()
    schema = build_case_note_schema()
    await repo.create_session(state, schema, ttl_sec=600)
    all_keys = [k.decode() if isinstance(k, bytes) else k for k in await fake_redis.keys("*")]
    assert all_keys, "Expected at least one key after session creation"
    for key in all_keys:
        assert key.startswith("sena:rp_voice:"), f"Key {key!r} does not start with sena:rp_voice:"
    assert not any(k.startswith("sena:onboarding:") for k in all_keys)


@pytest.mark.asyncio
async def test_ttl_set_on_state(fake_redis, repo) -> None:
    state = _make_state()
    schema = build_case_note_schema()
    await repo.create_session(state, schema, ttl_sec=300)
    ttl = await fake_redis.ttl("sena:rp_voice:session:s-1")
    assert ttl > 0


@pytest.mark.asyncio
async def test_ws_lock_contention(repo) -> None:
    acquired_first = await repo.acquire_ws_lock("s-1", ttl_sec=30)
    acquired_second = await repo.acquire_ws_lock("s-1", ttl_sec=30)
    assert acquired_first is True
    assert acquired_second is False
    await repo.release_ws_lock("s-1")
    acquired_after_release = await repo.acquire_ws_lock("s-1", ttl_sec=30)
    assert acquired_after_release is True
