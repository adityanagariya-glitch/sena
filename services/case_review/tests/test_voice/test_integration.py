"""Integration tests — stub genai.live.connect, verify field capture flow."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

try:
    import fakeredis.aioredis as fakeredis_aio
    _HAS_FAKEREDIS = True
except ImportError:
    _HAS_FAKEREDIS = False

pytestmark = pytest.mark.skipif(not _HAS_FAKEREDIS, reason="fakeredis not installed")


@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def repo(fake_redis):
    from voice.state_repo import VoiceStateRepo
    return VoiceStateRepo(fake_redis)


@pytest.mark.asyncio
async def test_update_field_then_finish_emits_session_complete(repo) -> None:
    from voice.schema import build_case_note_schema
    from voice.state import CaseNoteVoiceState
    from voice.tools import ToolDispatcher

    state = CaseNoteVoiceState(
        session_id="s-integ",
        case_note_id="cn-integ",
        worker_id="w-1",
        client_id="liam-1",
    )
    schema = build_case_note_schema()
    await repo.create_session(state, schema, ttl_sec=600)

    emitted: list[dict] = []

    async def _emit(event: dict) -> None:
        emitted.append(event)

    ws = MagicMock()
    ws.send_text = AsyncMock()

    d = ToolDispatcher(websocket=ws, session_id="s-integ", repo=repo, schema=schema, emit=_emit)

    for sec, fld, val in [
        ("shift", "shift_date", "2026-05-21"),
        ("shift", "shift_time", "07:00-15:00"),
        ("shift", "worker_position", "Support Worker"),
        ("summary", "describe", "Uneventful morning shift."),
        ("activities", "assisted", "breakfast, personal care"),
        ("wellbeing", "mood", "calm"),
    ]:
        result = await d.dispatch("update_field", {"section": sec, "field": fld, "value": val})
        assert result["ok"] is True

    result = await d.dispatch(
        "finish_session",
        {"confirmation_transcript": "yes all done with everything"},
    )
    assert result["ok"] is True
    assert d.step_completed is True

    sent = [json.loads(c.args[0]) for c in ws.send_text.call_args_list]
    types = [e["type"] for e in sent]
    assert "session_complete" in types

    complete_event = next(e for e in sent if e["type"] == "session_complete")
    payload = complete_event.get("payload", {})
    assert "shift_date" in payload


@pytest.mark.asyncio
async def test_prefilled_fields_not_re_asked(repo) -> None:
    """Pre-filled fields appear in prompt's current_page_values so agent skips them."""
    from voice.schema import build_case_note_schema
    from voice.session_bootstrap import SessionBootstrap
    from voice.state import CaseNoteVoiceState
    from voice.prompt_builder import build_system_prompt

    schema = build_case_note_schema()
    state = CaseNoteVoiceState(
        session_id="s-prefill",
        case_note_id="cn-1",
        worker_id="w-1",
        client_id="liam-1",
    )
    state.set_field("shift", "shift_date", "2026-05-21", source="prefill", confidence=1.0, turn_id=0)
    state.set_field("activities", "assisted", "morning routine", source="prefill", confidence=1.0, turn_id=0)

    bootstrap = SessionBootstrap.from_initial_values(
        {
            "shift": {"shift_date": "2026-05-21"},
            "activities": {"assisted": "morning routine"},
        },
        readonly_paths=[],
        worker_display_name=None,
    )
    prompt = build_system_prompt(schema, state, bootstrap=bootstrap)

    live_state_start = prompt.find("[LIVE_STATE_JSON]")
    live_state_end = prompt.find("[/LIVE_STATE_JSON]")
    live_block = prompt[live_state_start:live_state_end]

    assert "2026-05-21" in live_block
    assert "morning routine" in live_block


@pytest.mark.asyncio
async def test_no_evaluate_call_in_finish_session(repo) -> None:
    """finish_session must never trigger any pipeline or evaluate endpoint."""
    from voice.schema import build_case_note_schema
    from voice.state import CaseNoteVoiceState
    from voice.tools import ToolDispatcher

    state = CaseNoteVoiceState(
        session_id="s-neval",
        case_note_id="cn-1",
        worker_id="w-1",
        client_id="liam-1",
    )
    schema = build_case_note_schema()
    await repo.create_session(state, schema, ttl_sec=600)

    emitted: list[dict] = []

    async def _emit(event: dict) -> None:
        emitted.append(event)

    ws = MagicMock()
    ws.send_text = AsyncMock()
    d = ToolDispatcher(websocket=ws, session_id="s-neval", repo=repo, schema=schema, emit=_emit)

    for sec, fld, val in [
        ("shift", "shift_date", "2026-05-21"),
        ("shift", "shift_time", "07:00-15:00"),
        ("shift", "worker_position", "Support Worker"),
        ("summary", "describe", "Night shift."),
        ("activities", "assisted", "personal care"),
        ("wellbeing", "mood", "anxious"),
    ]:
        await d.dispatch("update_field", {"section": sec, "field": fld, "value": val})

    with patch("pipeline.graph.run_pipeline") as mock_pipeline:
        result = await d.dispatch(
            "finish_session",
            {"confirmation_transcript": "yep all done"},
        )
        mock_pipeline.assert_not_called()

    assert result["ok"] is True
