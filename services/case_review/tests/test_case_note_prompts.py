"""Regression tests for the case-note voice prompt templates.

Covers `voice/prompts/case_note_system.py` (base template, §5a/§5 rules) and
`voice/prompts/steps/staff_case_note.py` (step fragment). No existing test
file covers prompt content — `test_case_note_client.py` tests the HTTP stub,
not the rendered prompt — so this file is justified per the implementation
plan (docs/onboarding-voice-issues-implementation-plan-2026-07-01.md, item
"New test file needed").
"""
from __future__ import annotations

from shared.src.sena_common.voice import build_system_prompt
from shared.src.sena_common.voice.turn_payload import (
    Participant,
    StepInfo,
    TurnPayload,
    VisibleField,
)

from voice.prompts import registry as case_review_registry


def _case_note_turn() -> TurnPayload:
    return TurnPayload(
        participant=Participant(first_name="Alice", display_name="Alice Smith"),
        step=StepInfo(id="staff_case_note", label="Case Note", number=1),
        bootstrap_mode="new_user",
        prior_steps={},
        visible_fields=[
            VisibleField(
                path="summary.summaryOfShift",
                label="Summary of Shift",
                type="textarea",
                required=True,
                readonly=False,
                value=None,
            ),
        ],
    )


def test_case_note_boolean_false_rule_present() -> None:
    """§5a exception carving out boolean fields from the never-re-ask rule."""
    out = build_system_prompt(_case_note_turn(), registry=case_review_registry)
    assert "Exception — boolean fields:" in out
    assert 'NOT mean "already answered."' in out


def test_case_note_speaks_before_finalize_note() -> None:
    """Global §5 rule + the staff_case_note step fragment must both reorder
    the closing line to precede `finalize_note`, not follow it."""
    out = build_system_prompt(_case_note_turn(), registry=case_review_registry)
    # Global rule present.
    assert "Speak BEFORE calling `finalize_note`, never after." in out
    # Step fragment no longer contains the bare post-hoc pattern.
    assert "On `{ok: true}` →" not in out
    # Step fragment contains the reordered say-then-call pattern.
    assert (
        'say *"Done! Great shift — have a good one! 👋"* THEN, in that same '
        "turn, call `finalize_note(confirmation_transcript=<their exact words>)`."
    ) in out
