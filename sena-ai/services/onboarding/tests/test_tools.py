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
    # The gate that fires depends on schema structure: section-min fires before
    # recompute_completion when a required repeatable section has 0 rows.
    assert "unfilled" in result.get("error", "") or result.get("error") == "section_min_unmet"
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


# ── add_repeatable_row ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_repeatable_row_pins_focus_to_new_index(
    dispatcher, seeded_repo
) -> None:
    result = await dispatcher.dispatch(
        "add_repeatable_row", {"section_id": "emergency_contacts"}
    )
    assert result["ok"] is True
    new_index = result["new_index"]

    state = await seeded_repo.get_state("sid-1")
    assert state.focused_section == "emergency_contacts"
    assert state.focused_repeatable_index == new_index


@pytest.mark.asyncio
async def test_add_repeatable_row_emits_repeatable_section_entered(
    dispatcher, emitted
) -> None:
    result = await dispatcher.dispatch(
        "add_repeatable_row", {"section_id": "emergency_contacts"}
    )
    assert result["ok"] is True

    types_emitted = [e["type"] for e in emitted]
    assert "row_added" in types_emitted
    assert "repeatable_section_entered" in types_emitted

    entered = next(e for e in emitted if e["type"] == "repeatable_section_entered")
    assert entered["section_id"] == "emergency_contacts"
    assert entered["row_index"] == result["new_index"]
    assert entered["intent"] == "next"


# ── unknown tool ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_unknown_tool(dispatcher) -> None:
    result = await dispatcher.dispatch("frobnicate", {})
    assert result["ok"] is False
    assert "unknown tool" in result["error"]


# ── service_address ← home_address auto-copy ─────────────────────────────────


@pytest.mark.asyncio
async def test_service_address_auto_copies_when_flag_default_true(
    dispatcher, seeded_repo, emitted
) -> None:
    """service_same_as_home defaults to true in the schema; filling
    home_address should mirror into service_address without an explicit flag
    set."""
    for fld, val in [
        ("address", "1 Example St"),
        ("state", "NSW"),
        ("city", "Sydney"),
        ("zip_code", "2000"),
    ]:
        await dispatcher.dispatch(
            "update_field",
            {"section": "home_address", "field": fld, "value": val},
        )

    state = await seeded_repo.get_state("sid-1")
    svc = state.values.get("service_address") or {}
    assert svc.get("address", {}).get("value") == "1 Example St"
    assert svc.get("state", {}).get("value") == "NSW"
    assert svc.get("city", {}).get("value") == "Sydney"
    assert svc.get("zip_code", {}).get("value") == "2000"

    # The mirror-side fields should be tagged source=app, not voice
    assert svc["address"]["source"] == "app"

    # Each mirrored field surfaces a field_updated event with auto_copied_from
    auto_copy_events = [
        e for e in emitted
        if e.get("type") == "field_updated"
        and e.get("section") == "service_address"
        and e.get("auto_copied_from") == "home_address"
    ]
    assert len(auto_copy_events) == 4


@pytest.mark.asyncio
async def test_service_address_no_copy_when_flag_explicit_false(
    dispatcher, seeded_repo, emitted
) -> None:
    """When the user explicitly says 'service address differs from home',
    home_address fills must NOT mirror into service_address."""
    await dispatcher.dispatch(
        "update_field",
        {
            "section": "service_address",
            "field": "service_same_as_home",
            "value": "false",
            "cross_section_intent": True,
        },
    )
    for fld, val in [
        ("address", "1 Home St"),
        ("state", "NSW"),
        ("city", "Sydney"),
        ("zip_code", "2000"),
    ]:
        await dispatcher.dispatch(
            "update_field",
            {"section": "home_address", "field": fld, "value": val},
        )

    state = await seeded_repo.get_state("sid-1")
    svc = state.values.get("service_address") or {}
    # The flag is recorded, but address fields must remain unset
    assert svc.get("service_same_as_home", {}).get("value") is False
    assert svc.get("address") is None or svc["address"].get("value") is None


@pytest.mark.asyncio
async def test_service_address_copies_after_flag_flip_to_true(
    dispatcher, seeded_repo
) -> None:
    """Flag explicitly set to True after home_address is already populated
    must trigger the mirror on the flag write itself."""
    for fld, val in [
        ("address", "42 Main Rd"),
        ("state", "VIC"),
        ("city", "Melbourne"),
        ("zip_code", "3000"),
    ]:
        await dispatcher.dispatch(
            "update_field",
            {"section": "home_address", "field": fld, "value": val},
        )
    # Flip flag explicitly true (cross-section write)
    await dispatcher.dispatch(
        "update_field",
        {
            "section": "service_address",
            "field": "service_same_as_home",
            "value": "true",
            "cross_section_intent": True,
        },
    )

    state = await seeded_repo.get_state("sid-1")
    svc = state.values["service_address"]
    assert svc["address"]["value"] == "42 Main Rd"
    assert svc["state"]["value"] == "VIC"
    assert svc["city"]["value"] == "Melbourne"
    assert svc["zip_code"]["value"] == "3000"


# ── feature flag ────────────────────────────────────────────────────────────


def test_cross_screen_context_flag_defaults_on() -> None:
    """Regression: the cross-screen context bucket lookup must be ON by
    default. Symptom of OFF: agent re-asks the participant's name on every
    new screen because prior_pages stays empty."""
    from onboarding.core.settings import settings
    assert settings.onboarding_cross_screen_context_enabled is True


# ── repeatable auto-pin (cross_section_blocked recovery) ─────────────────────


@pytest.mark.asyncio
async def test_repeatable_update_auto_pins_focus_when_other_section_focused(
    dispatcher, seeded_repo, emitted
) -> None:
    """Regression for the 'emergency contact update loop' bug. When focus is
    pinned to a non-repeatable section and the agent writes into a repeatable
    section without first calling enter_repeatable_section, the dispatcher
    must auto-pin instead of returning cross_section_blocked. Otherwise the
    agent re-asks the user the same field over and over."""
    # Pin focus to a non-repeatable section (e.g., basics)
    state = await seeded_repo.get_state("sid-1")
    state.focused_section = "basics"
    state.focused_repeatable_index = None
    await seeded_repo.save_state(state, ttl_sec=3600)

    result = await dispatcher.dispatch(
        "update_field",
        {
            "section": "emergency_contacts",
            "field": "name",
            "value": "Sarah Brown",
            "repeatable_index": 0,
        },
    )
    assert result["ok"] is True

    state_after = await seeded_repo.get_state("sid-1")
    assert state_after.focused_section == "emergency_contacts"
    assert state_after.focused_repeatable_index == 0
    assert state_after.values["emergency_contacts"][0]["name"]["value"] == "Sarah Brown"

    # The auto-pin emits an implicit-intent repeatable_section_entered event
    entered = [
        e for e in emitted
        if e.get("type") == "repeatable_section_entered"
        and e.get("intent") == "implicit"
    ]
    assert len(entered) >= 1


@pytest.mark.asyncio
async def test_non_repeatable_cross_section_still_blocked_without_intent(
    dispatcher, seeded_repo
) -> None:
    """Auto-pin is for repeatable targets only. Non-repeatable cross-section
    writes must still be rejected without explicit cross_section_intent so
    the strictness fix from the prior session is preserved."""
    state = await seeded_repo.get_state("sid-1")
    state.focused_section = "basics"
    state.focused_repeatable_index = None
    await seeded_repo.save_state(state, ttl_sec=3600)

    result = await dispatcher.dispatch(
        "update_field",
        {
            "section": "home_address",  # non-repeatable, different section
            "field": "address",
            "value": "1 Example St",
        },
    )
    assert result["ok"] is False
    assert result["rejection"]["code"] == "cross_section_blocked"


# ── M7: Field-Render-After-Validation Invariant ──────────────────────────────


@pytest.mark.asyncio
async def test_field_updated_NOT_emitted_on_validation_failure(
    dispatcher, emitted,
) -> None:
    """M7 invariant — a rejected value must NEVER produce a field_updated
    event. If it did, the Flutter UI would render an uncommitted value.
    """
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "email", "value": "not-an-email", "confidence": 1.0},
    )
    assert result["ok"] is False
    field_updates = [e for e in emitted if e.get("type") == "field_updated"]
    assert field_updates == [], (
        f"field_updated leaked on validation failure: {field_updates}"
    )


@pytest.mark.asyncio
async def test_field_updated_NOT_emitted_on_low_confidence(
    dispatcher, emitted,
) -> None:
    """M7 invariant — CONFIRM_REQUIRED must not produce a field_updated event.
    The value is in limbo until the user explicitly confirms.
    """
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Jane Smith", "confidence": 0.6},
    )
    assert result["ok"] is False
    assert result["rejection"]["code"] == "CONFIRM_REQUIRED"
    field_updates = [e for e in emitted if e.get("type") == "field_updated"]
    assert field_updates == [], (
        f"field_updated leaked on CONFIRM_REQUIRED: {field_updates}"
    )


@pytest.mark.asyncio
async def test_field_updated_emitted_only_after_full_pass(
    dispatcher, emitted,
) -> None:
    """M7 positive case — a valid, high-confidence capture MUST emit
    exactly one field_updated event with the committed value.
    """
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Aditya Nagariya", "confidence": 0.99},
    )
    assert result["ok"] is True
    field_updates = [e for e in emitted if e.get("type") == "field_updated"]
    assert len(field_updates) == 1
    assert field_updates[0]["value"] == "Aditya Nagariya"


# ── M1: PENDING_CONFIRMATION lock ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_confidence_sets_pending_confirmation_lock(
    dispatcher, seeded_repo,
) -> None:
    """M1 — A CONFIRM_REQUIRED response must write state.pending_confirmation
    so future update_field calls for OTHER fields are blocked.
    """
    await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Jane Smith", "confidence": 0.6},
    )
    state = await seeded_repo.get_state("sid-1")
    assert state.pending_confirmation is not None
    assert state.pending_confirmation["section"] == "basics"
    assert state.pending_confirmation["field"] == "full_name"
    assert state.pending_confirmation["heard_value"] == "Jane Smith"


@pytest.mark.asyncio
async def test_pending_lock_blocks_unrelated_update_field(
    dispatcher, seeded_repo, emitted,
) -> None:
    """M1 — While pending_confirmation is set, update_field for ANY OTHER
    field is rejected with PENDING_CONFIRMATION_LOCKED.
    """
    # Step 1: trigger the lock with a low-confidence capture.
    await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Jane Smith", "confidence": 0.6},
    )
    emitted.clear()

    # Step 2: try to update a DIFFERENT field while locked.
    # C2 — cross-section / cross-row calls are now DEFERRED (buffered),
    # not hard-rejected with PENDING_CONFIRMATION_LOCKED.
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "email", "value": "x@y.com", "confidence": 1.0},
    )
    assert result["ok"] is False
    assert result["rejection"]["code"] == "DEFERRED"
    assert result["rejection"]["blocking_field"] == "full_name"
    field_updates = [e for e in emitted if e.get("type") == "field_updated"]
    assert field_updates == []


@pytest.mark.asyncio
async def test_pending_lock_clears_on_confirmation_commit(
    dispatcher, seeded_repo,
) -> None:
    """M1 — Re-submitting the SAME field at high confidence clears the lock
    and commits the value.
    """
    # Step 1: lock the field with a low-confidence attempt.
    await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Jane Smith", "confidence": 0.6},
    )
    state = await seeded_repo.get_state("sid-1")
    assert state.pending_confirmation is not None

    # Step 2: user said yes — re-commit at high confidence.
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Jane Smith", "confidence": 1.0},
    )
    assert result["ok"] is True
    state = await seeded_repo.get_state("sid-1")
    assert state.pending_confirmation is None


# ── M5: Conditional follow-up driver ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_interpreter_required_unlocks_interpreter_language(
    dispatcher, seeded_repo,
) -> None:
    """M5 — Setting basics.interpreter_required=true must write
    state.next_forced_field = {section: basics, field: interpreter_language}.
    """
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "interpreter_required", "value": "true", "confidence": 1.0},
    )
    assert result["ok"] is True
    state = await seeded_repo.get_state("sid-1")
    assert state.next_forced_field == {
        "section": "basics",
        "field": "interpreter_language",
    }


@pytest.mark.asyncio
async def test_filling_forced_field_clears_directive(
    dispatcher, seeded_repo,
) -> None:
    """M5 — After the forced field is filled, next_forced_field clears."""
    # Unlock the dependent.
    await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "interpreter_required", "value": "true", "confidence": 1.0},
    )
    state = await seeded_repo.get_state("sid-1")
    assert state.next_forced_field is not None

    # Fill the forced dependent.
    await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "interpreter_language", "value": "Gujarati", "confidence": 1.0},
    )
    state = await seeded_repo.get_state("sid-1")
    assert state.next_forced_field is None


# ── M3: Stricter email validator ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_email_disposable_domain_rejected(
    dispatcher, emitted,
) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "email", "value": "foo@mailinator.com", "confidence": 1.0},
    )
    assert result["ok"] is False
    assert result["rejection"]["code"] == "email_disposable"
    field_updates = [e for e in emitted if e.get("type") == "field_updated"]
    assert field_updates == []


@pytest.mark.asyncio
async def test_email_too_many_labels_rejected(
    dispatcher, emitted,
) -> None:
    """M3 — domain with 4+ labels (a.b.c.d.com) must be rejected as malformed."""
    result = await dispatcher.dispatch(
        "update_field",
        {
            "section": "basics", "field": "email",
            "value": "x@torproject.dev.mrrobot.com.au.example",
            "confidence": 1.0,
        },
    )
    assert result["ok"] is False
    assert result["rejection"]["code"] == "email_invalid"


# ── C1: Same-row sibling bypass for PENDING_CONFIRMATION lock ────────────────


@pytest.fixture
def medical_schema() -> StepSchema:
    return StepSchema.model_validate_json(
        (FIXTURES / "schema_medical_information.json").read_text()
    )


@pytest_asyncio.fixture
async def medical_dispatcher(fake_redis, medical_schema, emitted):
    repo = FormStateRepo(fake_redis)
    state = FormState(
        session_id="sid-med",
        step_id=medical_schema.step_id,
        participant_id="p-1",
    )
    state.recompute_completion(medical_schema)
    await repo.create_session(state, medical_schema, ttl_sec=3600)

    async def capture(evt: dict) -> None:
        emitted.append(evt)

    return ToolDispatcher(
        websocket=None,
        session_id="sid-med",
        repo=repo,
        schema=medical_schema,
        emit=capture,
    )


@pytest.mark.asyncio
async def test_C1_same_row_sibling_bypasses_lock(medical_dispatcher, emitted) -> None:
    """C1 — Sibling fields in the SAME (section, repeatable_index) commit
    even while the row's primary field is locked pending confirmation.
    This permits the parallel-dictation case (one medication row's
    medication+dosage+frequency in a single user breath)."""
    # Lock the row by capturing the medication name at low confidence.
    r1 = await medical_dispatcher.dispatch(
        "update_field",
        {
            "section": "medications",
            "field": "medication",
            "value": "Azithromycin",
            "confidence": 0.8,
            "repeatable_index": 0,
        },
    )
    assert r1["ok"] is False
    assert r1["rejection"]["code"] == "CONFIRM_REQUIRED"

    # Sibling field in the same row — high confidence — MUST commit.
    r2 = await medical_dispatcher.dispatch(
        "update_field",
        {
            "section": "medications",
            "field": "dosage",
            "value": "500mg",
            "confidence": 1.0,
            "repeatable_index": 0,
        },
    )
    assert r2["ok"] is True, f"sibling rejected: {r2}"


@pytest.mark.asyncio
async def test_C1_different_row_still_blocked(medical_dispatcher) -> None:
    """C1 negative — same section, DIFFERENT row is not a same-row sibling.
    C2: it is now buffered with code DEFERRED instead of hard-rejected
    with PENDING_CONFIRMATION_LOCKED."""
    await medical_dispatcher.dispatch(
        "update_field",
        {
            "section": "medications",
            "field": "medication",
            "value": "Aspirin",
            "confidence": 0.8,
            "repeatable_index": 0,
        },
    )
    r2 = await medical_dispatcher.dispatch(
        "update_field",
        {
            "section": "medications",
            "field": "medication",
            "value": "Tylenol",
            "confidence": 1.0,
            "repeatable_index": 1,
        },
    )
    assert r2["ok"] is False
    assert r2["rejection"]["code"] == "DEFERRED"


# ── C2: Deferred batch buffer ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_C2_cross_row_call_during_lock_is_deferred_not_rejected(
    medical_dispatcher, fake_redis,
) -> None:
    """C2 — Cross-row call during a lock is buffered with code: DEFERRED
    instead of hard-rejected with PENDING_CONFIRMATION_LOCKED."""
    # Lock medications[0] with a low-confidence capture.
    await medical_dispatcher.dispatch(
        "update_field",
        {"section": "medications", "field": "medication", "value": "Aspirin",
         "confidence": 0.8, "repeatable_index": 0},
    )
    # Different ROW — must be DEFERRED, not LOCKED.
    r = await medical_dispatcher.dispatch(
        "update_field",
        {"section": "medications", "field": "medication", "value": "Tylenol",
         "confidence": 1.0, "repeatable_index": 1},
    )
    assert r["ok"] is False
    assert r["rejection"]["code"] == "DEFERRED"


@pytest.mark.asyncio
async def test_C2_deferred_calls_drain_when_lock_clears(
    medical_dispatcher, fake_redis,
) -> None:
    """C2 — When the locked field commits at high confidence, the buffered
    calls drain and apply. The success response includes deferred_applied."""
    # Lock medications[0].medication.
    await medical_dispatcher.dispatch(
        "update_field",
        {"section": "medications", "field": "medication", "value": "Aspirin",
         "confidence": 0.8, "repeatable_index": 0},
    )
    # Cross-row call gets buffered.
    await medical_dispatcher.dispatch(
        "update_field",
        {"section": "medications", "field": "medication", "value": "Tylenol",
         "confidence": 1.0, "repeatable_index": 1},
    )
    # User confirms Aspirin → lock clears → buffered call should drain.
    confirm = await medical_dispatcher.dispatch(
        "update_field",
        {"section": "medications", "field": "medication", "value": "Aspirin",
         "confidence": 1.0, "repeatable_index": 0},
    )
    assert confirm["ok"] is True
    assert "deferred_applied" in confirm
    assert len(confirm["deferred_applied"]) == 1
    assert confirm["deferred_applied"][0]["ok"] is True
    assert confirm["deferred_applied"][0]["section"] == "medications"


# ── V4: Section-min gate in advance_step ────────────────────────────────────


@pytest.fixture
def requirements_schema() -> StepSchema:
    return StepSchema.model_validate_json(
        (FIXTURES / "schema_participant_requirements.json").read_text()
    )


@pytest_asyncio.fixture
async def requirements_repo(fake_redis, requirements_schema) -> FormStateRepo:
    repo = FormStateRepo(fake_redis)
    state = FormState(
        session_id="sid-req",
        step_id=requirements_schema.step_id,
        participant_id="p-req",
    )
    state.recompute_completion(requirements_schema)
    await repo.create_session(state, requirements_schema, ttl_sec=3600)
    return repo


@pytest_asyncio.fixture
async def requirements_dispatcher(
    requirements_repo, requirements_schema, emitted
) -> ToolDispatcher:
    async def capture(evt: dict) -> None:
        emitted.append(evt)

    return ToolDispatcher(
        websocket=None,
        session_id="sid-req",
        repo=requirements_repo,
        schema=requirements_schema,
        emit=capture,
    )


async def _fill_requirements_scalar_fields(dispatcher: ToolDispatcher) -> None:
    """Fill all required scalar fields in the requirements section so
    recompute_completion is satisfied and the section-min gate is reached."""
    scalar_fills = [
        ("requirements", "cultural_considerations", None, "Respectful of culture"),
        ("requirements", "most_important", None, "Independence"),
        ("requirements", "goals", None, "Learn to cook"),
        ("requirements", "hobbies_interests", None, "Gardening"),
    ]
    for sec, fld, _idx, val in scalar_fills:
        await dispatcher.dispatch(
            "update_field", {"section": sec, "field": fld, "value": val, "confidence": 1.0}
        )
    # multi_enum fields require the 'values' array form
    await dispatcher.dispatch(
        "update_field",
        {
            "section": "requirements",
            "field": "mode_of_communication",
            "values": ["Verbal (spoken)"],
            "confidence": 1.0,
        },
    )
    await dispatcher.dispatch(
        "update_field",
        {
            "section": "requirements",
            "field": "style_of_communication",
            "values": ["I prefer clear, simple language"],
            "confidence": 1.0,
        },
    )


@pytest.mark.asyncio
async def test_advance_step_blocked_by_section_min(
    requirements_dispatcher, requirements_repo, requirements_schema, emitted, monkeypatch
) -> None:
    """V4 — advance_step must block and NOT fire the webhook when morning_routine
    and evening_routine have 0 rows (min=1 each)."""
    monkeypatch.setattr(tools_module, "fire_webhook", None)  # must not be called

    await _fill_requirements_scalar_fields(requirements_dispatcher)

    result = await requirements_dispatcher.dispatch(
        "advance_step", {"confirmation_transcript": "yes I'm done"}
    )

    assert result["ok"] is False
    assert result["error"] == "section_min_unmet"
    assert "morning_routine" in result["sections"] or "evening_routine" in result["sections"]
    assert requirements_dispatcher.step_completed is False

    # field_skipped_warning must have been emitted
    warning_events = [e for e in emitted if e["type"] == "field_skipped_warning"]
    assert len(warning_events) >= 1
    warning = warning_events[-1]
    assert warning["missing_count"] >= 1
    section_ids_in_warning = [f["section_id"] for f in warning["missing_fields"]]
    assert any(sid in section_ids_in_warning for sid in ("morning_routine", "evening_routine"))


# ── S6: Sentinel field_id guard ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_field_sentinel_field_id_rejected(
    dispatcher, seeded_repo, emitted,
) -> None:
    """Gemini echoing __section_min__ must be rejected without touching state."""
    state_before = await seeded_repo.get_state("sid-1")
    values_before = state_before.model_dump(mode="json")["values"]

    result = await dispatcher.dispatch(
        "update_field",
        {
            "section": "basics",
            "field": "__section_min__",
            "value": "anything",
            "confidence": 1.0,
        },
    )

    assert result["ok"] is False
    assert result["error"] == "sentinel_field_id"
    # Nothing emitted — state not touched
    assert emitted == []
    state_after = await seeded_repo.get_state("sid-1")
    assert state_after.model_dump(mode="json")["values"] == values_before


# ── S6: Enum validation via FieldSpec ────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_field_enum_invalid_via_field_spec(
    requirements_dispatcher, requirements_repo, emitted,
) -> None:
    """update_field with a value not in multi_enum options returns enum_invalid."""
    result = await requirements_dispatcher.dispatch(
        "update_field",
        {
            "section": "requirements",
            "field": "mode_of_communication",
            "values": ["Walkie Talkies"],
            "confidence": 1.0,
        },
    )

    assert result["ok"] is False
    rejection = result["rejection"]
    assert rejection["code"] == "enum_invalid"
    assert "allowed_values" in rejection
    assert "Verbal (spoken)" in rejection["allowed_values"]
    # No field_updated event emitted on rejection
    field_updates = [e for e in emitted if e.get("type") == "field_updated"]
    assert field_updates == []
    # validation_rejection WS event emitted with allowed_values (so Flutter can show picker)
    vr_events = [e for e in emitted if e.get("type") == "validation_rejection"]
    assert len(vr_events) == 1
    vr = vr_events[0]
    assert vr["section_id"] == "requirements"
    assert vr["field_id"] == "mode_of_communication"
    assert vr["code"] == "enum_invalid"
    assert "allowed_values" in vr
    assert "Verbal (spoken)" in vr["allowed_values"]


@pytest.mark.asyncio
async def test_update_field_valid_enum_value_accepted(
    requirements_dispatcher, requirements_repo,
) -> None:
    """update_field with a valid multi_enum value returns ok=True."""
    result = await requirements_dispatcher.dispatch(
        "update_field",
        {
            "section": "requirements",
            "field": "mode_of_communication",
            "values": ["Verbal (spoken)"],
            "confidence": 1.0,
        },
    )
    assert result["ok"] is True
    state = await requirements_repo.get_state("sid-req")
    saved = state.values["requirements"]["mode_of_communication"]["value"]
    assert saved == ["Verbal (spoken)"]


@pytest.mark.asyncio
async def test_advance_step_passes_when_routines_filled(
    requirements_dispatcher, requirements_repo, requirements_schema, emitted, monkeypatch
) -> None:
    """V4 — section-min gate must NOT trigger when each routine has >= 1 row."""
    fired: dict = {}

    async def fake_fire_webhook(**kwargs: object) -> bool:
        fired.update(kwargs)
        return True

    monkeypatch.setattr(tools_module, "fire_webhook", fake_fire_webhook)

    await _fill_requirements_scalar_fields(requirements_dispatcher)

    # Add one row to each repeatable section (satisfies min=1)
    for section_id in ("morning_routine", "evening_routine"):
        await requirements_dispatcher.dispatch(
            "update_field",
            {
                "section": section_id,
                "field": "description",
                "value": "Wake up",
                "repeatable_index": 0,
                "confidence": 1.0,
            },
        )

    result = await requirements_dispatcher.dispatch(
        "advance_step", {"confirmation_transcript": "yes that's everything"}
    )

    # The section-min gate must NOT have triggered
    assert result.get("error") != "section_min_unmet", (
        f"section_min gate fired unexpectedly: {result}"
    )
    # Webhook must have been called
    assert fired.get("event") == "onboarding.session.completed"
