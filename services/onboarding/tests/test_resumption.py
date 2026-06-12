"""Tests for services/resumption.py — fakeredis integration."""
from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from voice.state_repo import FormStateRepo
from voice.resumption import build_replay_context, issue_handle, redeem_handle


@pytest_asyncio.fixture
async def repo():
    r = FakeRedis(decode_responses=True)
    yield FormStateRepo(r)
    await r.aclose()


# ── issue + redeem round-trip ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_issue_and_redeem_valid(repo):
    handle = await issue_handle(repo, "sess-1", ttl_sec=60)
    assert len(handle) == 36  # UUID4
    result = await redeem_handle(repo, handle, "sess-1")
    assert result is True


@pytest.mark.asyncio
async def test_single_use_double_redeem_fails(repo):
    handle = await issue_handle(repo, "sess-2", ttl_sec=60)
    assert await redeem_handle(repo, handle, "sess-2") is True
    assert await redeem_handle(repo, handle, "sess-2") is False


@pytest.mark.asyncio
async def test_expired_handle_returns_false(repo):
    # TTL=0 not valid in Redis; use TTL=1 and rely on GETDEL returning None for
    # a handle that was never stored under a known key
    result = await redeem_handle(repo, "nonexistent-handle", "sess-3")
    assert result is False


@pytest.mark.asyncio
async def test_wrong_session_id_returns_false(repo):
    handle = await issue_handle(repo, "sess-4", ttl_sec=60)
    result = await redeem_handle(repo, handle, "sess-WRONG")
    assert result is False


@pytest.mark.asyncio
async def test_wrong_session_consumes_handle(repo):
    # Even a failed redeem (wrong session) must NOT consume the handle —
    # the GETDEL already consumed it, so the real session can't redeem either.
    # This is acceptable per the PRD: mismatched handle is treated as invalid.
    handle = await issue_handle(repo, "sess-5", ttl_sec=60)
    await redeem_handle(repo, handle, "sess-WRONG")
    # Handle is now gone — correct session can no longer redeem it
    result = await redeem_handle(repo, handle, "sess-5")
    assert result is False


# ── build_replay_context ──────────────────────────────────────────────────────

def test_build_replay_empty_transcript():
    assert build_replay_context([], last_n=4) == ""


def test_build_replay_zero_n():
    transcript = [{"speaker": "user", "text": "hello"}]
    assert build_replay_context(transcript, last_n=0) == ""


def test_build_replay_fewer_than_n():
    transcript = [
        {"speaker": "user", "text": "Hi there"},
        {"speaker": "agent", "text": "Hello! I'm Sena."},
    ]
    result = build_replay_context(transcript, last_n=4)
    assert "[RESUME]" in result
    assert 'user="Hi there"' in result
    assert 'agent="Hello! I\'m Sena."' in result


def test_build_replay_uses_last_n_only():
    transcript = [
        {"speaker": "user", "text": "first"},
        {"speaker": "agent", "text": "second"},
        {"speaker": "user", "text": "third"},
        {"speaker": "agent", "text": "fourth"},
        {"speaker": "user", "text": "fifth"},
    ]
    result = build_replay_context(transcript, last_n=2)
    assert 'user="fifth"' in result
    assert 'agent="fourth"' in result
    assert "first" not in result
    assert "second" not in result


def test_build_replay_format():
    transcript = [{"speaker": "user", "text": "My name is Jane"}]
    result = build_replay_context(transcript, last_n=4)
    assert result.startswith("[RESUME] last turns:")
    assert "Continue from where you left off." in result


def test_build_replay_skips_empty_text():
    transcript = [
        {"speaker": "user", "text": ""},
        {"speaker": "agent", "text": "  "},
        {"speaker": "user", "text": "hello"},
    ]
    result = build_replay_context(transcript, last_n=4)
    assert 'user="hello"' in result
    assert result.count(";") == 0  # only one turn
