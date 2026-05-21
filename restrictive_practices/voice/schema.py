"""Build the StepSchema for the case-note voice assistant."""
from __future__ import annotations

from voice.schema_spec import FieldSpec, FieldType, SectionSpec, StepSchema

# Fields marked readonly are displayed to the agent but update_field is rejected for them.
_READONLY_FIELDS = {"shift.case_note_id", "shift.worker_id", "shift.client_id"}


def build_case_note_schema() -> StepSchema:
    """Return the StepSchema for the 7-section case note form.

    Sections mirror the logical grouping in CaseNoteInput. voice_coverage is
    empty (all fields are voice-eligible).
    """
    return StepSchema(
        step_id="case_note",
        step_label="Case Note",
        progress_percent=0,
        sections=[
            SectionSpec(
                id="shift",
                label="Shift Information",
                fields=[
                    FieldSpec(id="shift_date", type=FieldType.date, label="Shift Date", required=True),
                    FieldSpec(id="shift_time", type=FieldType.text, label="Shift Time", required=True),
                    FieldSpec(id="worker_position", type=FieldType.text, label="Worker Position", required=True),
                ],
            ),
            SectionSpec(
                id="summary",
                label="Summary of Shift",
                fields=[
                    FieldSpec(id="describe", type=FieldType.textarea, label="Shift Summary", required=True),
                ],
            ),
            SectionSpec(
                id="activities",
                label="Activities & Skill-Building",
                fields=[
                    FieldSpec(id="assisted", type=FieldType.textarea, label="Activities Assisted With", required=True),
                    FieldSpec(id="practised_skill", type=FieldType.textarea, label="Skills Practised", required=False),
                    FieldSpec(
                        id="participants_level_of_independence",
                        type=FieldType.text,
                        label="Participant Independence Level",
                        required=False,
                    ),
                    FieldSpec(id="observations", type=FieldType.textarea, label="Observations", required=False),
                ],
            ),
            SectionSpec(
                id="wellbeing",
                label="Wellbeing & Behaviour",
                fields=[
                    FieldSpec(id="mood", type=FieldType.textarea, label="Mood & Behaviour", required=True),
                    FieldSpec(id="behavioural_events", type=FieldType.textarea, label="Behavioural Events", required=False),
                    FieldSpec(id="any_concerns", type=FieldType.boolean, label="Any Concerns", required=False),
                ],
            ),
            SectionSpec(
                id="outcomes",
                label="Outcomes",
                fields=[
                    FieldSpec(id="what_went_well", type=FieldType.textarea, label="What Went Well", required=False),
                    FieldSpec(
                        id="what_needs_further_support",
                        type=FieldType.textarea,
                        label="What Needs Further Support",
                        required=False,
                    ),
                    FieldSpec(id="participant_comments", type=FieldType.textarea, label="Participant Comments", required=False),
                ],
            ),
            SectionSpec(
                id="safety",
                label="Safety",
                fields=[
                    FieldSpec(
                        id="medication_reminders_given",
                        type=FieldType.boolean,
                        label="Medication Reminders Given",
                        required=False,
                    ),
                    FieldSpec(
                        id="safety_hazards_observed",
                        type=FieldType.textarea,
                        label="Safety Hazards Observed",
                        required=False,
                    ),
                    FieldSpec(id="any_injuries", type=FieldType.boolean, label="Any Injuries", required=False),
                    FieldSpec(
                        id="injury_description",
                        type=FieldType.textarea,
                        label="Injury Description",
                        required=True,
                        visible_if={"any_injuries": True},
                    ),
                    FieldSpec(id="uploaded_documents", type=FieldType.text, label="Uploaded Documents", required=False),
                ],
            ),
            SectionSpec(
                id="incidents",
                label="Notes & Incidents",
                fields=[
                    FieldSpec(id="carer_feedback", type=FieldType.textarea, label="Carer Feedback", required=False),
                    FieldSpec(id="incident_occurred", type=FieldType.boolean, label="Incident Occurred", required=False),
                ],
            ),
        ],
        voice_coverage=[],  # empty = all fields voice-eligible
    )
