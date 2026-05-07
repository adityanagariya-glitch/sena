"""
Tests for the Phase C tool dispatcher.

These tests bypass Gemini entirely — they exercise ToolDispatcher directly
with a FakeRedis-backed FormStateRepo, a captured emit function in place of
the WebSocket, and a monkeypatched `fire_webhook` to assert delivery.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import StepSchema
from onboarding.repositories.state_repo import FormStateRepo
from onboarding.services import tools as tools_module
from onboarding.services.tools import FUNCTION_DECLS, ToolDispatcher

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def personal_schema() -> StepSchema:
    return StepSchema.model_validate_json(
        (FIXTURES / "schema_personal_information.json").read_text()
    )


@pytest_asyncio.fixture
async def seeded_repo(fake_redis, personal_schema):
    """Repo with a fresh FormState + schema saved for session_id='sid-1'."""
    repo = FormStateRepo(fake_redis)
    state = FormState(
        session_id="sid-1",
        step_id=personal_schema.step_id,
        participant_id="p-1",
    )
    state.recompute_completion(personal_schema)
    await repo.create_session(state, personal_schema, ttl_sec=3600)
    return repo


@pytest.fixture
def emitted() -> list[dict]:
    """Captures every event the dispatcher would send over the WS."""
    return []


@pytest_asyncio.fixture
async def dispatcher(seeded_repo, personal_schema, emitted):
    async def capture(evt: dict) -> None:
        emitted.append(evt)

    return ToolDispatcher(
        websocket=None,  # unused — capture() replaces send_text
        session_id="sid-1",
        repo=seeded_repo,
        schema=personal_schema,
        emit=capture,
    )


# ── FUNCTION_DECLS shape ─────────────────────────────────────────────────────


def test_function_decls_cover_all_handlers() -> None:
    names = {d["name"] for d in FUNCTION_DECLS}
    assert names == {
        "update_field",
        "get_session_context",
        "advance_step",
        "escalate_incident",
        "add_repeatable_row",
        "enter_repeatable_section",
        "exit_repeatable_section",
        "request_unknown_section",
    }
    for decl in FUNCTION_DECLS:
        assert decl["parameters"]["type"] == "object"
        assert "properties" in decl["parameters"]


# ── update_field ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_field_happy_path(dispatcher, seeded_repo, emitted) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Aditya Nagariya", "confidence": 0.95},
    )
    assert result["ok"] is True
    assert result["required_filled"] == 1

    state = await seeded_repo.get_state("sid-1")
    assert state.values["basics"]["full_name"]["value"] == "Aditya Nagariya"
    assert state.values["basics"]["full_name"]["confidence"] == 0.95

    types_emitted = [e["type"] for e in emitted]
    assert "field_updated" in types_emitted
    assert "state" in types_emitted


@pytest.mark.asyncio
async def test_update_field_coerces_boolean(dispatcher, seeded_repo) -> None:
    await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "interpreter_required", "value": "yes"},
    )
    state = await seeded_repo.get_state("sid-1")
    assert state.values["basics"]["interpreter_required"]["value"] is True


@pytest.mark.asyncio
async def test_update_field_unknown_section(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "does_not_exist", "field": "x", "value": "y"},
    )
    assert result["ok"] is False
    assert "unknown section" in result["error"]


@pytest.mark.asyncio
async def test_update_field_unknown_field(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "does_not_exist", "value": "y"},
    )
    assert result["ok"] is False
    assert "not in section" in result["error"]


@pytest.mark.asyncio
async def test_update_field_repeatable_with_index(dispatcher, seeded_repo) -> None:
    await dispatcher.dispatch(
        "update_field",
        {
            "section": "emergency_contacts",
            "field": "name",
            "value": "Sarah Brown",
            "repeatable_index": 0,
        },
    )
    await dispatcher.dispatch(
        "update_field",
        {
            "section": "emergency_contacts",
            "field": "name",
            "value": "Tom Brown",
            "repeatable_index": 1,
        },
    )
    state = await seeded_repo.get_state("sid-1")
    contacts = state.values["emergency_contacts"]
    assert isinstance(contacts, list)
    assert len(contacts) == 2
    assert contacts[0]["name"]["value"] == "Sarah Brown"
    assert contacts[1]["name"]["value"] == "Tom Brown"


@pytest.mark.asyncio
async def test_update_field_repeatable_exceeds_max(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {
            "section": "emergency_contacts",
            "field": "name",
            "value": "X",
            "repeatable_index": 10,  # max is 5
        },
    )
    assert result["ok"] is False
    assert "exceeds max" in result["error"]


# ── get_session_context ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_context_reports_progress(dispatcher) -> None:
    await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Aditya Nagariya"},
    )
    result = await dispatcher.dispatch("get_session_context", {})
    assert result["ok"] is True
    assert result["filled"]["basics.full_name"] == "Aditya Nagariya"
    assert "basics.email" in result["missing_required"]
    assert result["required_filled"] >= 1


# ── advance_step ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_advance_step_rejects_when_incomplete(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "advance_step", {"confirmation_transcript": "that's all"}
    )
    assert result["ok"] is False
    assert "unfilled" in result["error"]
    assert dispatcher.step_completed is False


@pytest.mark.asyncio
async def test_advance_step_rejects_empty_confirmation_transcript(dispatcher) -> None:
    result = await dispatcher.dispatch("advance_step", {})
    assert result["ok"] is False
    assert result["rejection"]["code"] == "missing_confirmation"


@pytest.mark.asyncio
async def test_advance_step_rejects_short_confirmation_transcript(dispatcher) -> None:
    # "ok" is 2 chars — below the 3-char minimum
    result = await dispatcher.dispatch("advance_step", {"confirmation_transcript": "ok"})
    assert result["ok"] is False
    assert result["rejection"]["code"] == "missing_confirmation"


@pytest.mark.asyncio
async def test_advance_step_cross_field_gate_blocks_on_rejection(
    dispatcher, seeded_repo, personal_schema, emitted, monkeypatch
) -> None:
    from onboarding.services.validators.base import ValidationRejection

    fake_rejection = ValidationRejection(
        code="emergency_email_duplicate",
        reason_human="Emergency contacts must have unique email addresses.",
    )
    monkeypatch.setattr(tools_module, "validate_step_complete", lambda s, st: [fake_rejection])

    # Fill all required fields so the completion gate passes
    fills = {
        ("basics", "full_name"): "Aditya Nagariya",
        ("basics", "email"): "a@b.com",
        ("basics", "phone"): "+61400000000",
        ("basics", "date_of_birth"): "1990-01-01",
        ("basics", "gender"): "Male",
        ("basics", "about_me"): "hello",
        ("basics", "preferred_language"): "English",
        ("basics", "interpreter_required"): "false",
        ("home_address", "address"): "1 Example St",
        ("home_address", "state"): "NSW",
        ("home_address", "city"): "Sydney",
        ("home_address", "zip_code"): "2000",
    }
    for (sec, fld), val in fills.items():
        await dispatcher.dispatch("update_field", {"section": sec, "field": fld, "value": val})
    for field, value in [
        ("name", "Sarah"), ("relation", "Parent"),
        ("email", "s@b.com"), ("phone", "+61400111222"),
    ]:
        await dispatcher.dispatch(
            "update_field",
            {"section": "emergency_contacts", "field": field, "value": value, "repeatable_index": 0},
        )

    result = await dispatcher.dispatch(
        "advance_step", {"confirmation_transcript": "yes I'm done"}
    )
    assert result["ok"] is False
    assert result["rejection"]["code"] == "cross_field_invariants_failed"


@pytest.mark.asyncio
async def test_advance_step_emits_validation_rejection_for_cross_field_violation(
    dispatcher, seeded_repo, personal_schema, emitted, monkeypatch
) -> None:
    from onboarding.services.validators.base import ValidationRejection

    fake_rejection = ValidationRejection(
        code="plan_end_before_start",
        reason_human="Plan end date must be after start date.",
    )
    monkeypatch.setattr(tools_module, "validate_step_complete", lambda s, st: [fake_rejection])
    # Fill all required fields so the completion check passes
    fills = {
        ("basics", "full_name"): "Aditya Nagariya",
        ("basics", "email"): "a@b.com",
        ("basics", "phone"): "+61400000000",
        ("basics", "date_of_birth"): "1990-01-01",
        ("basics", "gender"): "Male",
        ("basics", "about_me"): "hello",
        ("basics", "preferred_language"): "English",
        ("basics", "interpreter_required"): "false",
        ("home_address", "address"): "1 Example St",
        ("home_address", "state"): "NSW",
        ("home_address", "city"): "Sydney",
        ("home_address", "zip_code"): "2000",
    }
    for (sec, fld), val in fills.items():
        await dispatcher.dispatch("update_field", {"section": sec, "field": fld, "value": val})
    for field, value in [
        ("name", "Sarah"), ("relation", "Parent"),
        ("email", "s@b.com"), ("phone", "+61400111222"),
    ]:
        await dispatcher.dispatch(
            "update_field",
            {"section": "emergency_contacts", "field": field, "value": value, "repeatable_index": 0},
        )

    result = await dispatcher.dispatch(
        "advance_step", {"confirmation_transcript": "yes, that's everything"}
    )
    assert result["ok"] is False
    assert result["rejection"]["code"] == "cross_field_invariants_failed"
    validation_events = [e for e in emitted if e["type"] == "validation_rejection"]
    assert len(validation_events) >= 1
    assert validation_events[0]["section_id"] == "_aggregate"


@pytest.mark.asyncio
async def test_advance_step_fires_webhook_when_complete(
    dispatcher, seeded_repo, personal_schema, emitted, monkeypatch
) -> None:
    # Fill every field visible to recompute_completion as "required"
    fills = {
        ("basics", "full_name"): "Aditya Nagariya",
        ("basics", "email"): "a@b.com",
        ("basics", "phone"): "+61400000000",
        ("basics", "date_of_birth"): "1990-01-01",
        ("basics", "gender"): "Male",
        ("basics", "about_me"): "hello",
        ("basics", "preferred_language"): "English",
        ("basics", "interpreter_required"): "false",
        ("home_address", "address"): "1 Example St",
        ("home_address", "state"): "NSW",
        ("home_address", "city"): "Sydney",
        ("home_address", "zip_code"): "2000",
    }
    for (sec, fld), val in fills.items():
        await dispatcher.dispatch(
            "update_field", {"section": sec, "field": fld, "value": val}
        )

    # Repeatable: at least one emergency contact (all 4 fields)
    for field, value in [
        ("name", "Sarah"),
        ("relation", "Parent"),
        ("email", "s@b.com"),
        ("phone", "+61400111222"),
    ]:
        await dispatcher.dispatch(
            "update_field",
            {
                "section": "emergency_contacts",
                "field": field,
                "value": value,
                "repeatable_index": 0,
            },
        )

    # Stub the webhook so we don't hit the network
    fired: dict = {}

    async def fake_fire_webhook(**kwargs):
        fired.update(kwargs)
        return True

    monkeypatch.setattr(tools_module, "fire_webhook", fake_fire_webhook)

    result = await dispatcher.dispatch(
        "advance_step", {"confirmation_transcript": "that's everything, thanks"}
    )
    assert result["ok"] is True
    assert result["webhook_delivered"] is True
    assert dispatcher.step_completed is True
    assert fired["event"] == "onboarding.session.completed"
    assert fired["payload"]["step"] == "personal_information"
    assert fired["payload"]["confirmation_transcript"] == "that's everything, thanks"

    state = await seeded_repo.get_state("sid-1")
    assert state.completed is True
    assert state.completed_at is not None

    assert any(e["type"] == "step_completed" for e in emitted)


# ── escalate_incident ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escalate_incident_appends_and_emits(dispatcher, seeded_repo, emitted) -> None:
    result = await dispatcher.dispatch(
        "escalate_incident",
        {"reason": "self_harm", "transcript_excerpt": "I feel unsafe."},
    )
    assert result["ok"] is True

    state = await seeded_repo.get_state("sid-1")
    assert len(state.escalations) == 1
    assert state.escalations[0].reason == "self_harm"
    assert state.escalations[0].transcript_excerpt == "I feel unsafe."

    escalated = [e for e in emitted if e["type"] == "escalated"]
    assert len(escalated) == 1
    assert escalated[0]["reason"] == "self_harm"


# ── unknown tool ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_unknown_tool(dispatcher) -> None:
    result = await dispatcher.dispatch("frobnicate", {})
    assert result["ok"] is False
    assert "unknown tool" in result["error"]
