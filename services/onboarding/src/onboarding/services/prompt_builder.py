"""
Builds the Gemini system instruction for an onboarding session.

Loads the markdown template from prompts/onboarding_system.md and substitutes
session-specific values using explicit string replacement — NOT str.format() —
to avoid conflicts with JSON curly braces inside the schema/state payloads.

Rule 1 / Rule 2 hygiene contract (state isolation + multi-page handoff) is
delivered through the [LIVE_STATE_JSON] block rendered into the prompt. The
agent is instructed to treat that block as the only authority for prior
context, so a fresh session on the same page cannot inherit a prior run's
chat memory.
"""
from __future__ import annotations

import json
from pathlib import Path

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import StepSchema
from onboarding.models.session_bootstrap import SessionBootstrap

_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "onboarding_system.md"


def _voice_coverage_section(voice_coverage: list[str]) -> str:
    if not voice_coverage:
        return ""
    paths = ", ".join(voice_coverage)
    return (
        "\nVOICE COVERAGE\n"
        f"You may ONLY call update_field for these fields: {paths}. "
        "Do not attempt to fill any field not in this list via voice."
    )


def _build_live_state_block(
    bootstrap: SessionBootstrap | None,
    state: FormState,
    schema: StepSchema,
) -> str:
    """Render the [LIVE_STATE_JSON] context block.

    This block is the SOLE authority for prior conversation context — Gemini is
    instructed in the prompt to treat it that way. Renders bootstrap fields
    (mode, current_page_values, readonly_paths, prior_pages, display_name) plus
    the live FormState values + completion stats.
    """
    completion = state.completion.model_dump() if state.completion else None
    payload = {
        "mode": (bootstrap.mode if bootstrap else "new_user"),
        "step_id": schema.step_id,
        "step_label": schema.step_label,
        "participant_display_name": (bootstrap.participant_display_name if bootstrap else None),
        "current_page_values": state.values,
        "readonly_paths": (bootstrap.readonly_paths if bootstrap else []),
        "prior_pages": (bootstrap.prior_pages if bootstrap else {}),
        "completion": completion,
    }
    return json.dumps(payload, default=str)


def build_system_prompt(
    schema: StepSchema,
    state: FormState,
    *,
    grounding_enabled: bool = False,
    screen_context_text: str | None = None,
    resume_context_text: str | None = None,
    bootstrap: SessionBootstrap | None = None,
) -> str:
    """
    Render the onboarding system prompt with the session schema and current state.

    Placeholders in the template (all prefixed/suffixed with __):
      __STEP_LABEL__         — human label for the current step
      __PROGRESS_PCT__       — integer percent through the full onboarding flow
      __SCHEMA_JSON__        — compact JSON of the StepSchema
      __STATE_JSON__         — compact JSON of values + completion (legacy)
      __LIVE_STATE_JSON__    — Rule 1/2 bootstrap envelope (mode, readonly,
                                prior_pages, current values). Authoritative.
      __BOOTSTRAP_MODE__     — convenience: bootstrap.mode value as a string
      __GROUNDING_SECTION__  — Google Search instruction when grounding is on
      __VOICE_COVERAGE_SECTION__ — voice-coverage restriction block (or empty)

    Optional dynamic sections appended after the template:
      screen_context_text   — injected as SCREEN CONTEXT block
      resume_context_text   — injected as RESUME CONTEXT block at session start
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    schema_json = schema.model_dump_json()

    # Compact state snapshot — only what the model needs to skip already-filled fields
    state_summary = {
        "values": state.values,
        "completion": state.completion.model_dump() if state.completion else None,
    }
    state_json = json.dumps(state_summary, default=str)

    live_state_json = _build_live_state_block(bootstrap, state, schema)
    bootstrap_mode = bootstrap.mode if bootstrap else "new_user"

    grounding_section = (
        "\nGROUNDING\n"
        "Google Search is available as a tool. When the participant asks an NDIS policy "
        "question you cannot answer from the schema or your training, use Google Search to "
        "provide a current, accurate answer. Cite the source briefly."
        if grounding_enabled
        else ""
    )

    voice_coverage_section = _voice_coverage_section(schema.voice_coverage)

    result = (
        template
        .replace("__STEP_LABEL__", schema.step_label)
        .replace("__PROGRESS_PCT__", str(schema.progress_percent))
        .replace("__SCHEMA_JSON__", schema_json)
        .replace("__STATE_JSON__", state_json)
        .replace("__LIVE_STATE_JSON__", live_state_json)
        .replace("__BOOTSTRAP_MODE__", bootstrap_mode)
        .replace("__GROUNDING_SECTION__", grounding_section)
        .replace("__VOICE_COVERAGE_SECTION__", voice_coverage_section)
    )

    if resume_context_text:
        result += f"\n\nRESUME CONTEXT\n{resume_context_text}"

    if screen_context_text:
        result += f"\n\nSCREEN CONTEXT\n{screen_context_text}"

    return result
