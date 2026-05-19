"""Tests for prompt_builder token interpolation.

Uses a minimal stub template injected via monkeypatch so tests are not
sensitive to the full onboarding_system.md content.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import FieldSpec, FieldType, SectionSpec, StepSchema
from onboarding.models.session_bootstrap import SessionBootstrap
from onboarding.services import prompt_builder as pb
from onboarding.services.prompt_builder import _compute_next_required_field


# ── Helpers ───────────────────────────────────────────────────────────────────

_STUB_TEMPLATE = (
    "__PARTICIPANT_NAME__ "
    "__NEXT_OPTIONAL_FIELD__ "
    "__STEP_LABEL__ "
    "__SCHEMA_JSON__ "
    "__STATE_JSON__ "
    "__LIVE_STATE_JSON__ "
    "__CROSS_SCREEN_SUMMARY__ "
    "__BOOTSTRAP_MODE__ "
    "__GROUNDING_SECTION__ "
    "__VOICE_COVERAGE_SECTION__ "
    "__NEXT_REQUIRED_FIELD__ "
    "__PENDING_VALIDATION_ERRORS__"
)


def _make_schema() -> StepSchema:
    return StepSchema(
        step_id="step1",
        step_label="Personal Info",
        progress_percent=10,
        sections=[
            SectionSpec(
                id="basics",
                label="Basics",
                fields=[
                    FieldSpec(id="full_name", type=FieldType.text, label="Full Name", required=True),
                    FieldSpec(id="nickname", type=FieldType.text, label="Nickname", required=False),
                ],
            )
        ],
    )


def _make_state() -> FormState:
    return FormState(session_id="sid-1", step_id="step1", participant_id="p-1")


def _build(schema, state, bootstrap=None, monkeypatch=None):
    if monkeypatch:
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = _STUB_TEMPLATE
        monkeypatch.setattr(pb, "_TEMPLATE_PATH", mock_path)
    return pb.build_system_prompt(schema, state, bootstrap=bootstrap)


# ── Token: __PARTICIPANT_NAME__ ───────────────────────────────────────────────


def test_participant_name_token_interpolated_when_present(monkeypatch) -> None:
    schema = _make_schema()
    state = _make_state()
    bootstrap = SessionBootstrap(participant_display_name="Jane")

    result = _build(schema, state, bootstrap=bootstrap, monkeypatch=monkeypatch)

    assert "Jane" in result
    assert "__PARTICIPANT_NAME__" not in result


def test_participant_name_token_falls_back_to_unknown_when_missing(monkeypatch) -> None:
    schema = _make_schema()
    state = _make_state()
    bootstrap = SessionBootstrap()  # no display name

    result = _build(schema, state, bootstrap=bootstrap, monkeypatch=monkeypatch)

    assert "unknown" in result
    assert "__PARTICIPANT_NAME__" not in result


# ── Token: __NEXT_OPTIONAL_FIELD__ ───────────────────────────────────────────


def test_next_optional_field_token_interpolated(monkeypatch) -> None:
    schema = _make_schema()
    state = _make_state()  # nickname not filled — next optional should appear

    result = _build(schema, state, monkeypatch=monkeypatch)

    assert "nickname" in result
    assert "__NEXT_OPTIONAL_FIELD__" not in result


def test_next_optional_field_token_empty_when_none_remain(monkeypatch) -> None:
    schema = _make_schema()
    state = _make_state()
    state.values["basics"] = {"nickname": {"value": "Nikki"}}  # optional filled

    result = _build(schema, state, monkeypatch=monkeypatch)

    # Token replaced with empty string; "nickname" may appear elsewhere in JSON
    assert "__NEXT_OPTIONAL_FIELD__" not in result
    # Specifically the token position should be empty (adjacent tokens collapse)
    assert "basics.nickname" not in result


# ── Section-min gate (V4): _compute_next_required_field ──────────────────────

_REQUIREMENTS_FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "schema_participant_requirements.json").read_text()
)

# requirements section has 6 required scalar fields that come before the
# repeatable sections in schema order.  Pre-fill them so the iterator reaches
# morning_routine / evening_routine.
_FILLED_REQUIREMENTS = {
    "cultural_considerations": {"value": "x"},
    "most_important": {"value": "x"},
    "goals": {"value": "x"},
    "hobbies_interests": {"value": "x"},
    "mode_of_communication": {"value": ["Verbal (spoken)"]},
    "style_of_communication": {"value": ["I prefer clear, simple language"]},
}


def _make_requirements_state(extra_values: dict | None = None) -> FormState:
    merged: dict = {"requirements": dict(_FILLED_REQUIREMENTS)}
    if extra_values:
        merged.update(extra_values)
    return FormState(
        session_id="test",
        step_id="participant_requirements",
        participant_id="p1",
        tenant_id="t1",
        values=merged,
    )


def test_routine_sections_are_optional_with_zero_rows() -> None:
    """morning_routine and evening_routine both have min=0 — empty is fine.
    next_required_field must NOT surface them when scalar fields are filled.
    """
    schema = StepSchema(**_REQUIREMENTS_FIXTURE)
    state = _make_requirements_state()
    result = _compute_next_required_field(schema, state)

    # Both routine sections optional (min=0); requirements scalar fields
    # filled by _FILLED_REQUIREMENTS — no required-field gap remains.
    assert result is None


def test_routine_sections_optional_one_row_still_ok() -> None:
    """Adding one morning_routine row is fine; the optional evening_routine
    remains empty and that is NOT a required-field gap."""
    schema = StepSchema(**_REQUIREMENTS_FIXTURE)
    state = _make_requirements_state(extra_values={
        "morning_routine": [{"description": {"value": "Wake up at 7am", "source": "voice"}}],
    })
    result = _compute_next_required_field(schema, state)

    assert result is None


def test_routine_sections_optional_both_filled() -> None:
    """Both routines populated — still no required gap."""
    schema = StepSchema(**_REQUIREMENTS_FIXTURE)
    state = _make_requirements_state(extra_values={
        "morning_routine": [{"description": {"value": "Wake up", "source": "voice"}}],
        "evening_routine": [{"description": {"value": "Wind down", "source": "voice"}}],
    })
    result = _compute_next_required_field(schema, state)

    assert result is None


# ── _render_pending_validation_errors: allowed_values (V3) ───────────────────


def test_render_pending_errors_includes_allowed_values() -> None:
    """allowed_values line appears when the error entry carries the key."""
    errors = [
        {
            "section_id": "requirements",
            "field_id": "mode_of_communication",
            "repeatable_index": None,
            "code": "enum_invalid",
            "reason_human": "That option isn't available.",
            "allowed_values": ["AAC Device", "Verbal (spoken)", "Written (text/email)"],
        }
    ]
    from onboarding.services.prompt_builder import _render_pending_validation_errors

    result = _render_pending_validation_errors(errors)
    assert "enum_invalid" in result
    assert "Allowed values:" in result
    assert "AAC Device" in result
    assert "Verbal (spoken)" in result


def test_render_pending_errors_no_allowed_values_for_non_enum() -> None:
    """No allowed_values line when the key is absent (non-enum errors)."""
    errors = [
        {
            "section_id": "basics",
            "field_id": "email",
            "repeatable_index": None,
            "code": "email_invalid",
            "reason_human": "Enter a valid email",
        }
    ]
    from onboarding.services.prompt_builder import _render_pending_validation_errors

    result = _render_pending_validation_errors(errors)
    assert "email_invalid" in result
    assert "Allowed values:" not in result


# ── Rule 13 and Rule 14 presence in rendered prompt ──────────────────────────


def test_build_system_prompt_contains_rule_13_and_14() -> None:
    """Rules 13 and 14 must appear in the rendered system prompt."""
    import json
    import pathlib

    from onboarding.models.form_state import FormState
    from onboarding.models.schema_spec import StepSchema
    from onboarding.services.prompt_builder import build_system_prompt

    schema_path = (
        pathlib.Path(__file__).parent.parent / "fixtures" / "schema_personal_information.json"
    )
    schema = StepSchema(**json.loads(schema_path.read_text()))
    state = FormState(
        session_id="t",
        step_id="personal_information",
        participant_id="p",
        tenant_id="t",
    )

    prompt = build_system_prompt(schema, state)
    assert "Rule 13" in prompt
    assert "enum_invalid" in prompt
    assert "allowed_values" in prompt
    assert "Rule 14" in prompt
    # Rule 14 now declares routines OPTIONAL (was: section_min_unmet mandate)
    assert "OPTIONAL" in prompt
    # New rules from 2026-05-19 fixes
    assert "Rule 19" in prompt  # read state before asking
    assert "Rule 20" in prompt  # readonly fields (email)
    assert "Rule 21" in prompt  # tone consistency


# ── visible_if pre-filter (regression: plan_manager bug 2026-05-19) ──────────


def test_visible_if_hidden_fields_removed_from_prompt_schema() -> None:
    """When plan_management != 'Plan Managed', the plan_manager /
    contact_email / billing_email fields MUST NOT appear in the schema
    section of the rendered system prompt. Without this filter, the agent
    asks for them even though the Flutter UI hides them. Confirmed by
    session 8431a840 (2026-05-19 19:08) where the agent asked
    'Would you like to add your plan manager's name now?' on a Self Managed
    plan.
    """
    import json
    from pathlib import Path
    from onboarding.models.schema_spec import StepSchema
    from onboarding.models.form_state import FormState
    from onboarding.services.prompt_builder import build_system_prompt

    fixtures = (
        Path(__file__).parent.parent / "fixtures"
        / "schema_ndis_plan_details.json"
    )
    schema = StepSchema.model_validate_json(fixtures.read_text())
    # State: plan_management is "Self Managed" — the conditional fields
    # must be hidden.
    state = FormState(
        session_id="t",
        step_id=schema.step_id,
        participant_id="p",
        tenant_id="t",
        values={"plan_info": {"plan_management": {"value": "Self Managed"}}},
    )
    prompt = build_system_prompt(schema, state)

    # Field IDs hidden by visible_if must NOT appear as a schema field
    # declaration (i.e. inside `"id": "..."`). Other mentions in prompt
    # examples are unavoidable but harmless — the model uses the schema
    # JSON section to know what fields exist.
    assert "\"id\":\"plan_manager\"" not in prompt and "\"id\": \"plan_manager\"" not in prompt, (
        "plan_manager field leaked into schema JSON despite Self Managed visible_if"
    )
    assert "\"id\":\"contact_email\"" not in prompt and "\"id\": \"contact_email\"" not in prompt, (
        "contact_email field leaked into schema JSON despite Self Managed visible_if"
    )
    assert "\"id\":\"billing_email\"" not in prompt and "\"id\": \"billing_email\"" not in prompt, (
        "billing_email field leaked into schema JSON despite Self Managed visible_if"
    )
    # Sanity: a non-hidden field IS present in the schema JSON
    assert "\"id\":\"ndis_number\"" in prompt or "\"id\": \"ndis_number\"" in prompt


def test_visible_if_fields_present_when_condition_satisfied() -> None:
    """Inverse: when plan_management == 'Plan Managed', the conditional
    fields MUST appear (so the agent CAN ask for them)."""
    import json
    from pathlib import Path
    from onboarding.models.schema_spec import StepSchema
    from onboarding.models.form_state import FormState
    from onboarding.services.prompt_builder import build_system_prompt

    fixtures = (
        Path(__file__).parent.parent / "fixtures"
        / "schema_ndis_plan_details.json"
    )
    schema = StepSchema.model_validate_json(fixtures.read_text())
    state = FormState(
        session_id="t",
        step_id=schema.step_id,
        participant_id="p",
        tenant_id="t",
        values={"plan_info": {"plan_management": {"value": "Plan Managed"}}},
    )
    prompt = build_system_prompt(schema, state)

    # Now the fields SHOULD appear in the schema JSON so the agent can ask.
    assert "\"id\":\"plan_manager\"" in prompt or "\"id\": \"plan_manager\"" in prompt
    assert "\"id\":\"contact_email\"" in prompt or "\"id\": \"contact_email\"" in prompt
    assert "\"id\":\"billing_email\"" in prompt or "\"id\": \"billing_email\"" in prompt


def test_screen_field_status_is_authoritative_over_schema() -> None:
    """When Flutter sends screen_field_status, ONLY fields whose dotted
    path is in that map appear in the rendered schema JSON. The schema may
    list more fields (universe of possibilities) but Flutter is the source
    of truth for what the participant actually sees on screen.

    Regression for production session a5b16b96 (2026-05-19 19:27):
    Flutter rendered plan_management but NOT plan_manager/contact_email/
    billing_email (hidden because plan_management = SELF_MANAGED). The
    agent asked for plan_manager anyway because the dynamically-supplied
    schema still listed them and lacked visible_if guards. Screen-state
    filtering eliminates this regardless of schema content.
    """
    import json
    from pathlib import Path
    from onboarding.models.schema_spec import StepSchema
    from onboarding.models.form_state import FormState
    from onboarding.services.prompt_builder import build_system_prompt

    fixtures = (
        Path(__file__).parent.parent / "fixtures"
        / "schema_ndis_plan_details.json"
    )
    schema = StepSchema.model_validate_json(fixtures.read_text())
    state = FormState(
        session_id="t",
        step_id=schema.step_id,
        participant_id="p",
        tenant_id="t",
    )
    # Flutter only rendered these fields (NDIS Plan Details on a Self
    # Managed plan). plan_manager / contact_email / billing_email are
    # absent — the agent must not see them either.
    screen_field_status = {
        "plan_info.ndis_number": "filled",
        "plan_info.plan_start": "filled",
        "plan_info.plan_end": "filled",
        "plan_info.plan_management": "filled",
        "ndis_goals.0.goal": "filled",
        "support_coordinator.coordinator_name": "filled",
        "support_coordinator.coordinator_email": "filled",
    }
    prompt = build_system_prompt(
        schema, state, screen_field_status=screen_field_status
    )

    # Fields absent from screen_field_status MUST be stripped from schema JSON
    assert "\"id\":\"plan_manager\"" not in prompt and "\"id\": \"plan_manager\"" not in prompt
    assert "\"id\":\"contact_email\"" not in prompt and "\"id\": \"contact_email\"" not in prompt
    assert "\"id\":\"billing_email\"" not in prompt and "\"id\": \"billing_email\"" not in prompt
    # And funding rows (also not in screen state) must be hidden
    assert "\"id\":\"daily_living\"" not in prompt and "\"id\": \"daily_living\"" not in prompt

    # But fields that ARE rendered MUST be present
    assert "\"id\":\"ndis_number\"" in prompt or "\"id\": \"ndis_number\"" in prompt
    assert "\"id\":\"plan_management\"" in prompt or "\"id\": \"plan_management\"" in prompt
    # Repeatable item_field matched by suffix
    assert "\"id\":\"goal\"" in prompt or "\"id\": \"goal\"" in prompt


def test_rule_21a_screen_source_of_truth_in_prompt() -> None:
    """Rule 21a (SCREEN is source of truth) is the explicit prompt rule
    paired with the server-side filter."""
    import json
    from pathlib import Path
    from onboarding.models.schema_spec import StepSchema
    from onboarding.models.form_state import FormState
    from onboarding.services.prompt_builder import build_system_prompt

    fixtures = (
        Path(__file__).parent.parent / "fixtures"
        / "schema_personal_information.json"
    )
    schema = StepSchema.model_validate_json(fixtures.read_text())
    state = FormState(
        session_id="t",
        step_id=schema.step_id,
        participant_id="p",
        tenant_id="t",
    )
    prompt = build_system_prompt(schema, state)
    assert "Rule 21a" in prompt
    assert "SCREEN" in prompt
