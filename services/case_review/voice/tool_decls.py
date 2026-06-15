"""Gemini Live function declarations for STAFF case-note dictation.

Injected into the shared engine via GeminiLiveSession(function_decls=...) and
ToolDispatcher(known_tools=..., submit_tool_name="finalize_note"). Differs from
the onboarding tool set: NO submit_step (a case note is a single screen, not a
multi-step flow) and NO escalate_incident; instead a single `finalize_note`
submits the completed note. NO add_row/delete_row — the case-note schema has no
repeatable sections (reportMedia is a UI file-upload, not voice-fillable).

Mobile remains authoritative (mobile-proxy): every tool call is forwarded to the
Flutter client, which applies it to FormState and returns {ok, ...}.
"""
from __future__ import annotations

from typing import Any

CASE_NOTE_FUNCTION_DECLS: list[dict[str, Any]] = [
    {
        "name": "update_field",
        "description": (
            "REQUIRED whenever the support worker dictates ANY value for the case "
            "note. Call this BEFORE speaking a confirmation. Examples: worker says "
            "'their mood was settled and calm' → update_field(section="
            "'wellbeingAndBehaviour', field='mood', value='Settled and calm'). "
            "Worker says 'yes there was an injury' → update_field(section="
            "'safetyAndHealth', field='anyInjuries', value='true'). Mobile validates "
            "and returns {ok:true} or {ok:false, reason} — speak reason verbatim on "
            "rejection."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Section id (e.g. 'summary', 'activitiesAndSkill', "
                        "'wellbeingAndBehaviour', 'outcomesAndProgress', "
                        "'safetyAndHealth', 'feedback', 'handover')."
                    ),
                },
                "field": {
                    "type": "string",
                    "description": (
                        "Exact field id (e.g. 'summaryOfShift', 'mood', "
                        "'anyInjuries', 'careFeedback'). Never invent variants."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": (
                        "Captured value ALWAYS as a string. Free text → the text. "
                        "Yes/no fields (anyConcerns, anyInjuries, anyIncident, "
                        "medicationReminderGiven, safetyHazardObserved) → "
                        "'true'/'false'. Never emit a raw boolean — wrap in quotes."
                    ),
                },
            },
            "required": ["section", "field", "value"],
        },
    },
    {
        "name": "clear_field",
        "description": "Blank out a previously-dictated field value.",
        "parameters": {
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "field": {"type": "string"},
            },
            "required": ["section", "field"],
        },
    },
    {
        "name": "get_current_state",
        "description": (
            "Re-read the full current case note. Call this if your most recent "
            "function_response is more than 3 turns ago and you are about to assert "
            "a field value, or if the worker says they changed something on screen. "
            "Mobile returns {ok:true, state:{...}} — treat it as the new source of "
            "truth, superseding the bootstrap state block."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "finalize_note",
        "description": (
            "Submit the completed case note. Call ONLY after the worker explicitly "
            "confirms they are done (human-in-the-loop — never auto-submit). Mobile "
            "checks every required field, returns {ok:true} or {ok:false, blockers:"
            "[{path,label,reason},...]}; on blockers, read the FIRST blocker's reason "
            "verbatim and ask the worker to fill it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "confirmation_transcript": {
                    "type": "string",
                    "description": "The worker's exact words confirming submission.",
                },
            },
            "required": ["confirmation_transcript"],
        },
    },
]

CASE_NOTE_KNOWN_TOOLS: frozenset[str] = frozenset(
    {"update_field", "clear_field", "get_current_state", "finalize_note"}
)
