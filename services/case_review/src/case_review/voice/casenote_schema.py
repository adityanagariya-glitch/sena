"""Voice StepSchema for the STAFF case-note form.

Authored to match the Flutter contract exactly — `CreateCaseNotePayload` in
`lib/features/case_notes/staff/data/models/case_note_request_payloads.dart`.
The nested payload objects (activitiesAndSkill, wellbeingAndBehaviour, …) are
flattened here into one `SectionSpec` per object; the `finalize_note` tool
(see `tool_decls.py`) re-nests section/field values back into the wire shape.

Field ids are the EXACT camelCase leaf keys the backend expects, so the
finalize mapper is a straight passthrough. `reportMedia` is intentionally
absent — it is a file-upload array, not voice-fillable; the ≥1-media gate is
enforced by the app backend at submit, not by the voice flow.
"""
from __future__ import annotations

from sena_common.voice.schema_spec import FieldSpec, FieldType, SectionSpec, StepSchema

_SECTIONS: list[SectionSpec] = [
    SectionSpec(
        id="summary",
        label="Summary of Shift",
        fields=[
            FieldSpec(id="summaryOfShift", type=FieldType.textarea, label="Summary of Shift"),
        ],
    ),
    SectionSpec(
        id="activitiesAndSkill",
        label="Activities & Skills",
        fields=[
            FieldSpec(id="assisted", type=FieldType.textarea, label="Assisted With"),
            FieldSpec(id="practisedSkill", type=FieldType.textarea, label="Skill Practised"),
            FieldSpec(
                id="participantsLevelOfIndependence",
                type=FieldType.textarea,
                label="Participant's Level of Independence",
            ),
            FieldSpec(id="observation", type=FieldType.textarea, label="Observation"),
        ],
    ),
    SectionSpec(
        id="wellbeingAndBehaviour",
        label="Wellbeing & Behaviour",
        fields=[
            FieldSpec(id="mood", type=FieldType.text, label="Mood"),
            FieldSpec(id="behaviouralEvents", type=FieldType.textarea, label="Behavioural Events"),
            FieldSpec(id="anyConcerns", type=FieldType.boolean, label="Any Concerns?"),
        ],
    ),
    SectionSpec(
        id="outcomesAndProgress",
        label="Outcomes & Progress",
        fields=[
            FieldSpec(id="whatWentWell", type=FieldType.textarea, label="What Went Well"),
            FieldSpec(id="furtherSupport", type=FieldType.textarea, label="Further Support Needed"),
            FieldSpec(
                id="participantsComments",
                type=FieldType.textarea,
                label="Participant's Comments",
            ),
        ],
    ),
    SectionSpec(
        id="safetyAndHealth",
        label="Safety & Health",
        fields=[
            FieldSpec(
                id="medicationReminderGiven",
                type=FieldType.boolean,
                label="Medication Reminder Given?",
            ),
            FieldSpec(
                id="safetyHazardObserved",
                type=FieldType.boolean,
                label="Safety Hazard Observed?",
            ),
            FieldSpec(id="anyInjuries", type=FieldType.boolean, label="Any Injuries?"),
            # Conditional: only collected when anyInjuries is true (matches the
            # Flutter `if (injuryDetails != null && isNotEmpty)` payload rule).
            FieldSpec(
                id="injuryDetails",
                type=FieldType.textarea,
                label="Injury Details",
                required=False,
                visible_if={"anyInjuries": True},
            ),
        ],
    ),
    SectionSpec(
        id="feedback",
        label="Feedback",
        fields=[
            FieldSpec(id="careFeedback", type=FieldType.textarea, label="Care Feedback"),
            FieldSpec(id="anyIncident", type=FieldType.boolean, label="Any Incident?"),
        ],
    ),
    SectionSpec(
        id="handover",
        label="Handover",
        fields=[
            # Required on the Flutter screen (validator requiredWithMinMax 5-1000)
            # even though the wire payload defaults handoverNote to '' — the form
            # will not submit without it, so the voice flow treats it as required.
            FieldSpec(id="handover", type=FieldType.textarea, label="Handover Note"),
        ],
    ),
]

# Every field is voice-eligible (the whole point of dictation). is_eligible()
# returns False on an empty voice_coverage, so this MUST be populated or the
# engine blocks all writes.
_VOICE_COVERAGE: list[str] = [
    f"{section.id}.{field.id}" for section in _SECTIONS for field in (section.fields or [])
]

CASE_NOTE_SCHEMA = StepSchema(
    step_id="staff_case_note",
    step_label="Case Note",
    progress_percent=0,
    sections=_SECTIONS,
    voice_coverage=_VOICE_COVERAGE,
)
