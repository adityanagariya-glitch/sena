"""
Tests for GeminiLiveSession._handle_screen_state — Step N-4 fix.

Verifies that v2 screen_state field_errors are mirrored into
state.pending_validation_errors so advance_step's gate has a single
source of truth regardless of whether Flutter also sends a
validation_failed control frame.

These tests call _handle_screen_state() directly, bypassing the full
Gemini Live connection. The Gemini session is replaced with an AsyncMock
that records send_realtime_input() calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from onboarding.models.form_state import FormState
from onboarding.repositories.state_repo import FormStateRepo
from onboarding.services.gemini_live import GeminiLiveSession


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_session(repo: FormStateRepo, session_id: str = "sid-1") -> GeminiLiveSession:
    ws = MagicMock()
    ws.send_text = AsyncMock()
    return GeminiLiveSession(
        websocket=ws,
        session_id=session_id,
        system_instruction="test",
        repo=repo,
    )


def _mock_gemini_session() -> AsyncMock:
    """Fake Gemini AsyncSession — only send_realtime_input needed."""
    session = AsyncMock()
    session.send_realtime_input = AsyncMock()
    return session


async def _seed(repo: FormStateRepo, session_id: str = "sid-1") -> FormState:
    state = FormState(session_id=session_id, step_id="personal_information", participant_id="p-1")
    await repo.save_state(state, ttl_sec=3600)
    return state


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seeded_repo(fake_redis):
    repo = FormStateRepo(fake_redis)
    await _seed(repo)
    return repo


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_v2_screen_state_with_field_errors_upserts_pending_validation_errors(
    seeded_repo,
) -> None:
    """field_errors in v2 payload → upserted into state.pending_validation_errors."""
    bridge = _make_session(seeded_repo)
    gemini = _mock_gemini_session()

    data = {
        "data": {
            "step_id": "personal_information",
            "field_status": {"basics.email": "invalid"},
            "field_errors": {"basics.email": "Must be a valid email address"},
        }
    }
    await bridge._handle_screen_state(gemini, data, version=2)

    state = await seeded_repo.get_state("sid-1")
    assert state is not None
    assert len(state.pending_validation_errors) == 1
    err = state.pending_validation_errors[0]
    assert err["section_id"] == "basics"
    assert err["field_id"] == "email"
    assert err["reason_human"] == "Must be a valid email address"
    assert err["code"] == "client_validation"
    assert err["repeatable_index"] is None

    # Gemini still received the screen text injection
    gemini.send_realtime_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_v2_screen_state_idempotent_on_repeated_same_field_error(
    seeded_repo,
) -> None:
    """Sending the same field error twice (with a different screen hash) does
    not duplicate the pending_validation_errors entry — upsert replaces it."""
    bridge = _make_session(seeded_repo)
    gemini = _mock_gemini_session()

    # First call
    data1 = {
        "data": {
            "step_id": "personal_information",
            "field_status": {"basics.email": "invalid"},
            "field_errors": {"basics.email": "Bad email"},
        }
    }
    await bridge._handle_screen_state(gemini, data1, version=2)

    # Second call — different hash (focused_field changed) but same field error
    data2 = {
        "data": {
            "step_id": "personal_information",
            "focused_field": "email",          # changes hash → dedup gate passes
            "field_status": {"basics.email": "invalid"},
            "field_errors": {"basics.email": "Bad email"},
        }
    }
    await bridge._handle_screen_state(gemini, data2, version=2)

    state = await seeded_repo.get_state("sid-1")
    assert state is not None
    # Still exactly one entry — the upsert replaced, not appended
    email_errors = [
        e for e in state.pending_validation_errors
        if e["section_id"] == "basics" and e["field_id"] == "email"
    ]
    assert len(email_errors) == 1


@pytest.mark.asyncio
async def test_v2_screen_state_with_no_field_errors_does_not_touch_pending_list(
    seeded_repo,
) -> None:
    """A v2 payload with no field_errors must not modify an existing
    pending_validation_errors list — only explicit field_errors can upsert."""
    # Seed an existing validation error directly on the state
    state = await seeded_repo.get_state("sid-1")
    state.pending_validation_errors = [
        {"section_id": "basics", "field_id": "phone", "repeatable_index": None,
         "code": "invalid_phone", "reason_human": "Bad phone"}
    ]
    await seeded_repo.save_state(state, ttl_sec=3600)

    bridge = _make_session(seeded_repo)
    gemini = _mock_gemini_session()

    data = {
        "data": {
            "step_id": "personal_information",
            "field_status": {"basics.phone": "filled"},
            # No field_errors key at all
        }
    }
    await bridge._handle_screen_state(gemini, data, version=2)

    state_after = await seeded_repo.get_state("sid-1")
    assert state_after is not None
    # Pre-existing error is untouched
    assert len(state_after.pending_validation_errors) == 1
    assert state_after.pending_validation_errors[0]["field_id"] == "phone"
