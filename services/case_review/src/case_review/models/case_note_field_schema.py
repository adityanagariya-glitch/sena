from __future__ import annotations

"""
Temporary case-note field schema for Phase C classify.

FREEZE WARNING: replace field list when Figma design arrives (blocker B3 in plan).
Do NOT hardcode field_id strings outside this file — always import from here.
"""

from typing import TypedDict


class FieldDef(TypedDict):
    field_id: str
    label: str
    description: str
    required: bool
    type: str  # date | time | string


FIELD_SCHEMA: list[FieldDef] = [
    {
        "field_id": "date_of_support",
        "label": "Date of Support",
        "description": "The date when the support was delivered (YYYY-MM-DD format).",
        "required": True,
        "type": "date",
    },
    {
        "field_id": "support_type",
        "label": "Support Type",
        "description": "The category of NDIS support provided (e.g. Daily Activities, Community Participation, Capacity Building).",
        "required": True,
        "type": "string",
    },
    {
        "field_id": "activities_provided",
        "label": "Activities Provided",
        "description": "Description of the specific support activities carried out during the session.",
        "required": True,
        "type": "string",
    },
    {
        "field_id": "participant_response",
        "label": "Participant Response",
        "description": "How the participant responded to the support — engagement, mood, cooperation.",
        "required": True,
        "type": "string",
    },
    {
        "field_id": "staff_observations",
        "label": "Staff Observations",
        "description": "General observations, concerns, or notable moments noted by the support worker.",
        "required": True,
        "type": "string",
    },
    {
        "field_id": "time_start",
        "label": "Time Start",
        "description": "Time the support session started (HH:MM 24hr format).",
        "required": False,
        "type": "time",
    },
    {
        "field_id": "time_end",
        "label": "Time End",
        "description": "Time the support session ended (HH:MM 24hr format).",
        "required": False,
        "type": "time",
    },
    {
        "field_id": "participant_goals",
        "label": "Participant Goals Addressed",
        "description": "Which of the participant's NDIS plan goals were worked toward in this session.",
        "required": False,
        "type": "string",
    },
    {
        "field_id": "progress_notes",
        "label": "Progress Notes",
        "description": "Specific progress made toward participant goals or skill development.",
        "required": False,
        "type": "string",
    },
    {
        "field_id": "incidents_observed",
        "label": "Incidents Observed",
        "description": "Any incidents, near-misses, behavioural events, injuries, or medication errors. Null if none.",
        "required": False,
        "type": "string",
    },
    {
        "field_id": "medications_administered",
        "label": "Medications Administered",
        "description": "Any medications given during the session including name and dose. Null if none.",
        "required": False,
        "type": "string",
    },
    {
        "field_id": "next_steps",
        "label": "Next Steps",
        "description": "Planned actions or focus areas for the next support session.",
        "required": False,
        "type": "string",
    },
]

REQUIRED_FIELD_IDS: list[str] = [f["field_id"] for f in FIELD_SCHEMA if f["required"]]

FIELD_BY_ID: dict[str, FieldDef] = {f["field_id"]: f for f in FIELD_SCHEMA}


def schema_as_text() -> str:
    """Render field schema as a structured text block for prompt injection."""
    lines: list[str] = []
    for f in FIELD_SCHEMA:
        req = "REQUIRED" if f["required"] else "optional"
        lines.append(f"- {f['field_id']} [{req}] ({f['type']}): {f['description']}")
    return "\n".join(lines)
