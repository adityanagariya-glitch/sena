from __future__ import annotations

from onboarding.models.turn_payload import (
    NextTarget,
    Participant,
    StepInfo,
    TurnPayload,
    VisibleField,
)
from onboarding.services.prompt_builder import build_system_prompt


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


def test_prompt_omits_step_fragment_for_unknown_step() -> None:
    """Unknown step.id → no fragment loaded, base template still renders."""
    tp = _minimal_turn()
    tp.step.id = "this_step_does_not_exist"
    out = build_system_prompt(tp)
    # __STEP_RULES__ placeholder must be replaced even when fragment missing.
    assert "__STEP_RULES__" not in out
    assert "Step-specific rules" not in out


def test_prompt_step_rules_placeholder_consumed() -> None:
    """Placeholder must never leak into the rendered prompt."""
    out = build_system_prompt(_minimal_turn())
    assert "__STEP_RULES__" not in out
