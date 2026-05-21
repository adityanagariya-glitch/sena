"""Tests for ToolDispatcher — 9 cases."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

try:
    import fakeredis.aioredis as fakeredis_aio
    _HAS_FAKEREDIS = True
except ImportError:
    _HAS_FAKEREDIS = False

from voice.schema import build_case_note_schema
from voice.state import CaseNoteVoiceState
from voice.state_repo import VoiceStateRepo
from voice.tools import FUNCTION_DECLS, ToolDispatcher

pytestmark = pytest.mark.skipif(not _HAS_FAKEREDIS, reason="fakeredis not installed")


@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def seeded_repo(fake_redis):
    repo = VoiceStateRepo(fake_redis)
    state = CaseNoteVoiceState(
        session_id="s-1",
        case_note_id="cn-1",
        worker_id="w-1",
        client_id="liam-1",
    )
    schema = build_case_note_schema()
    await repo.create_session(state, schema, ttl_sec=600)
    return repo


@pytest.fixture
def emitted():
    events: list[dict] = []
    return events


@pytest_asyncio.fixture
async def dispatcher(seeded_repo, emitted):
    ws = MagicMock()
    ws.send_text = AsyncMock()
    schema = build_case_note_schema()
    events = emitted

    async def _emit(event: dict) -> None:
        events.append(event)

    d = ToolDispatcher(
        websocket=ws,
        session_id="s-1",
        repo=seeded_repo,
        schema=schema,
        emit=_emit,
    )
    return d


def test_function_decls_cover_all_handlers() -> None:
    names = {d["name"] for d in FUNCTION_DECLS}
    assert "update_field" in names
    assert "clear_field" in names
    assert "get_session_context" in names
    assert "finish_session" in names
    assert "escalate_incident" in names
    assert "add_repeatable_row" not in names


@pytest.mark.asyncio
async def test_update_field_happy_path(dispatcher, seeded_repo, emitted) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "shift", "field": "shift_date", "value": "2026-05-21"},
    )
    assert result["ok"] is True
    state = await seeded_repo.get_state("s-1")
    assert state.values["shift"]["shift_date"]["value"] == "2026-05-21"
    # Events go through ws.send_text — check the mock's call list
    sent = [json.loads(c.args[0]) for c in dispatcher._ws.send_text.call_args_list]
    types = [e["type"] for e in sent]
    assert "field_updated" in types


@pytest.mark.asyncio
async def test_update_field_unknown_section(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "nonexistent", "field": "foo", "value": "bar"},
    )
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_update_field_unknown_field(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "shift", "field": "nonexistent_field", "value": "bar"},
    )
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_clear_field(dispatcher, seeded_repo) -> None:
    await dispatcher.dispatch(
        "update_field",
        {"section": "shift", "field": "shift_date", "value": "2026-05-21"},
    )
    result = await dispatcher.dispatch(
        "clear_field",
        {"section": "shift", "field": "shift_date"},
    )
    assert result["ok"] is True
    state = await seeded_repo.get_state("s-1")
    fv = state.values.get("shift", {}).get("shift_date")
    assert fv is None or fv.get("value") is None


@pytest.mark.asyncio
async def test_finish_session_rejects_when_required_missing(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "finish_session",
        {"confirmation_transcript": "yes that is everything done"},
    )
    assert result["ok"] is False
    assert "rejections" in result or "missing_required" in result


@pytest.mark.asyncio
async def test_finish_session_happy_path(dispatcher, seeded_repo, emitted) -> None:
    required_fields = [
        ("shift", "shift_date", "2026-05-21"),
        ("shift", "shift_time", "07:00-15:00"),
        ("shift", "worker_position", "Support Worker"),
        ("summary", "describe", "Morning shift."),
        ("activities", "assisted", "personal care"),
        ("wellbeing", "mood", "settled"),
    ]
    for sec, fld, val in required_fields:
        await dispatcher.dispatch("update_field", {"section": sec, "field": fld, "value": val})

    result = await dispatcher.dispatch(
        "finish_session",
        {"confirmation_transcript": "yes that is everything done"},
    )
    assert result["ok"] is True
    state = await seeded_repo.get_state("s-1")
    assert state.completed is True
    sent = [json.loads(c.args[0]) for c in dispatcher._ws.send_text.call_args_list]
    types = [e["type"] for e in sent]
    assert "session_complete" in types


@pytest.mark.asyncio
async def test_escalate_incident_appends_and_emits(dispatcher, seeded_repo, emitted) -> None:
    result = await dispatcher.dispatch(
        "escalate_incident",
        {"reason": "serious_injury", "transcript_excerpt": "participant fell and hit head"},
    )
    assert result["ok"] is True
    state = await seeded_repo.get_state("s-1")
    assert len(state.escalations) == 1
    rec = state.escalations[0]
    reason = rec.reason if hasattr(rec, "reason") else rec["reason"]
    assert reason == "serious_injury"
    sent = [json.loads(c.args[0]) for c in dispatcher._ws.send_text.call_args_list]
    types = [e["type"] for e in sent]
    assert "escalated" in types


@pytest.mark.asyncio
async def test_cross_field_rule_injury_description_required(dispatcher, seeded_repo) -> None:
    await dispatcher.dispatch(
        "update_field",
        {"section": "safety", "field": "any_injuries", "value": True},
    )
    result = await dispatcher.dispatch(
        "finish_session",
        {"confirmation_transcript": "yes everything is done"},
    )
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_dispatch_unknown_tool(dispatcher) -> None:
    result = await dispatcher.dispatch("add_repeatable_row", {"section": "foo"})
    assert result.get("ok") is False or "error" in result
