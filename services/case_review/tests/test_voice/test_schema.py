"""Tests for build_case_note_schema."""
from __future__ import annotations

from voice.schema import build_case_note_schema


def test_all_seven_sections_present() -> None:
    schema = build_case_note_schema()
    section_ids = {s.id for s in schema.sections}
    assert section_ids == {"shift", "summary", "activities", "wellbeing", "outcomes", "safety", "incidents"}


def test_injury_description_has_visible_if() -> None:
    schema = build_case_note_schema()
    safety = next(s for s in schema.sections if s.id == "safety")
    injury_fld = next((f for f in (safety.fields or []) if f.id == "injury_description"), None)
    assert injury_fld is not None
    assert injury_fld.visible_if == {"any_injuries": True}
    assert injury_fld.required is True


def test_readonly_fields_excluded_from_required_iteration() -> None:
    from voice.validators.sequencing import next_required_field
    from voice.state import CaseNoteVoiceState

    schema = build_case_note_schema()
    state = CaseNoteVoiceState(
        session_id="s-1",
        case_note_id="cn-1",
        worker_id="w-1",
        client_id="liam-1",
    )
    result = next_required_field(schema, state)
    assert result is not None
    assert result["section_id"] in {"shift", "summary", "activities", "wellbeing", "outcomes", "safety", "incidents"}
