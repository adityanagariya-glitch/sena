from __future__ import annotations

import pytest

from voice.turn_payload import (
    NextTarget,
    Participant,
    StepInfo,
    TurnPayload,
    VisibleField,
)
from voice.prompt_builder import build_system_prompt


def _minimal_turn() -> TurnPayload:
    return TurnPayload(
        participant=Participant(first_name="Jane", display_name="Jane Doe"),
        step=StepInfo(id="personal_information", label="Personal Details", number=1),
        bootstrap_mode="new_user",
        prior_steps={},
        visible_fields=[
            VisibleField(
                path="basics.full_name",
                label="Full Name",
                type="text",
                required=True,
                readonly=False,
                value=None,
            ),
        ],
        next_target=NextTarget(
            path="basics.full_name", label="Full Name", reason="next_required",
        ),
    )


def test_prompt_substitutes_first_name() -> None:
    out = build_system_prompt(_minimal_turn())
    assert "Jane" in out


def test_prompt_substitutes_step_label() -> None:
    out = build_system_prompt(_minimal_turn())
    assert "Personal Details" in out


def test_prompt_contains_turn_json_block() -> None:
    out = build_system_prompt(_minimal_turn())
    assert "<state>" in out
    assert "</state>" in out
    assert '"first_name":"Jane"' in out


def test_prompt_lists_all_six_tool_names() -> None:
    out = build_system_prompt(_minimal_turn())
    for name in (
        "update_field",
        "clear_field",
        "add_row",
        "delete_row",
        "submit_step",
        "escalate_incident",
    ):
        assert name in out


def test_prompt_no_legacy_placeholders_remain() -> None:
    out = build_system_prompt(_minimal_turn())
    for legacy in (
        "__SCHEMA_JSON__",
        "__STATE_JSON__",
        "__LIVE_STATE_JSON__",
        "__VALIDATOR_REMINDER__",
        "__PENDING_VALIDATION_ERRORS__",
        "__NEXT_REQUIRED_FIELD__",
        "__NEXT_OPTIONAL_FIELD__",
        "__CROSS_SCREEN_SUMMARY__",
        "__BOOTSTRAP_MODE__",
    ):
        assert legacy not in out, f"Legacy placeholder {legacy} still in prompt"


def test_prompt_first_name_empty_still_renders() -> None:
    tp = _minimal_turn()
    tp.participant.first_name = ""
    out = build_system_prompt(tp)
    # Empty first name is fine in the JSON; the prompt rule handles greeting.
    assert "first_name" in out


def test_prompt_includes_grounding_section_when_enabled() -> None:
    out = build_system_prompt(_minimal_turn(), grounding_enabled=True)
    assert "Google Search" in out


def test_prompt_includes_voice_coverage_block_when_provided() -> None:
    out = build_system_prompt(_minimal_turn(), voice_coverage=["basics.full_name"])
    assert "VOICE COVERAGE" in out
    assert "basics.full_name" in out


def test_prompt_includes_per_step_fragment_when_present() -> None:
    """personal_information.md ships with the repo — its rules must load."""
    out = build_system_prompt(_minimal_turn())
    assert "Step-specific rules — Personal Details" in out


def test_prompt_raises_for_unknown_step() -> None:
    """Unknown step.id → loud KeyError (D1), not a silent half-built prompt.

    Replaces the old silent-empty contract: a step_id with no registered
    fragment is a misconfiguration and must surface immediately.
    """
    tp = _minimal_turn()
    tp.step.id = "this_step_does_not_exist"
    with pytest.raises(KeyError):
        build_system_prompt(tp)


def test_prompt_step_rules_placeholder_consumed() -> None:
    """Placeholder must never leak into the rendered prompt."""
    out = build_system_prompt(_minimal_turn())
    assert "__STEP_RULES__" not in out


def test_prompt_mode_rules_placeholder_consumed() -> None:
    """__MODE_RULES__ must always be substituted, even with no mode file present."""
    out = build_system_prompt(_minimal_turn())
    assert "__MODE_RULES__" not in out


def test_prompt_fresh_mode_when_all_required_empty() -> None:
    """All required fields null → fresh-mode rules load."""
    out = build_system_prompt(_minimal_turn())
    assert "MODE: FRESH FORM" in out
    assert "MODE: UPDATE FORM" not in out


def test_prompt_update_mode_when_required_field_filled() -> None:
    """Any required non-readonly field with a value → update-mode rules load."""
    tp = _minimal_turn()
    tp.visible_fields[0].value = "Aditya Nagariya"
    out = build_system_prompt(tp)
    assert "MODE: UPDATE FORM" in out
    assert "MODE: FRESH FORM" not in out


def test_prompt_mode_ignores_readonly_filled_fields() -> None:
    """A filled readonly field must NOT flip the form into update-mode."""
    tp = _minimal_turn()
    tp.visible_fields[0].readonly = True
    tp.visible_fields[0].value = "locked-id-123"
    tp.visible_fields.append(
        VisibleField(
            path="basics.full_name",
            label="Full Name",
            type="text",
            required=True,
            readonly=False,
            value=None,
        )
    )
    out = build_system_prompt(tp)
    assert "MODE: FRESH FORM" in out


def _documents_turn() -> TurnPayload:
    return TurnPayload(
        participant=Participant(first_name="Jane", display_name="Jane Doe"),
        step=StepInfo(id="documents", label="Documents", number=4),
        bootstrap_mode="new_user",
        prior_steps={},
        visible_fields=[
            VisibleField(
                path="documents.abc123.document",
                label="NDIS Plan Document",
                type="file",
                required=True,
                readonly=False,
                value=None,
            ),
        ],
        next_target=NextTarget(
            path="documents.abc123.document",
            label="NDIS Plan Document",
            reason="next_required",
        ),
    )


def test_documents_step_forbids_all_mutation_tools_keeps_submit() -> None:
    """Documents is informational + submit-only: the step fragment must forbid
    every field-mutation tool (update_field, add_row, delete_row, clear_field)
    so the model never fires a tool_request the documents screen can't ACK,
    while submit_step stays the one allowed exception.
    """
    out = build_system_prompt(_documents_turn())
    # The documents fragment loaded.
    assert "Step-specific rules — Documents" in out
    # The widened ban naming all four mutation tools is present.
    assert "field-mutation tool" in out
    assert "`add_row`, `delete_row`, or `clear_field`" in out
    # submit_step explicitly preserved as the lone exception.
    assert "is the single exception" in out
    # Manual screen-edit must be acknowledged in words, never mirrored.
    assert "never mirror their action with a tool call" in out
