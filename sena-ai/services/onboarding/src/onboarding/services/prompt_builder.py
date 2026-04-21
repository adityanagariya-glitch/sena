"""
Builds the Gemini system instruction for an onboarding session.

Loads the markdown template from prompts/onboarding_system.md and substitutes
session-specific values using explicit string replacement — NOT str.format() —
to avoid conflicts with JSON curly braces inside the schema/state payloads.
"""
from __future__ import annotations

import json
from pathlib import Path

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import StepSchema

_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "onboarding_system.md"


def build_system_prompt(schema: StepSchema, state: FormState) -> str:
    """
    Render the onboarding system prompt with the session schema and current state.

    Placeholders in the template (all prefixed/suffixed with __):
      __STEP_LABEL__    — human label for the current step
      __PROGRESS_PCT__  — integer percent through the full onboarding flow
      __SCHEMA_JSON__   — compact JSON of the StepSchema
      __STATE_JSON__    — compact JSON of values + completion (no PII metadata)
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    schema_json = schema.model_dump_json()

    # Compact state snapshot — only what the model needs to skip already-filled fields
    state_summary = {
        "values": state.values,
        "completion": state.completion.model_dump() if state.completion else None,
    }
    state_json = json.dumps(state_summary, default=str)

    return (
        template
        .replace("__STEP_LABEL__", schema.step_label)
        .replace("__PROGRESS_PCT__", str(schema.progress_percent))
        .replace("__SCHEMA_JSON__", schema_json)
        .replace("__STATE_JSON__", state_json)
    )
