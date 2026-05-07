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

import structlog

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import StepSchema
from onboarding.models.session_bootstrap import SessionBootstrap
from onboarding.services.validators.sequencing import next_optional_field as _next_optional_field

log = structlog.get_logger(__name__)
_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "onboarding_system.md"


def _compute_next_required_field(schema: StepSchema, state: FormState) -> dict | None:
    """First required empty field in schema order — rendered into live-state JSON."""
    for section in schema.sections:
        is_rep = getattr(section, "is_repeatable", False)
        fields = section.item_fields if is_rep else (section.fields or [])
        sec_vals = state.values.get(section.id) or {}
        row: dict = (sec_vals[0] if isinstance(sec_vals, list) and sec_vals else {}) if is_rep else (sec_vals if isinstance(sec_vals, dict) else {})
        for field in fields:
            if not field.required:
                continue
            if field.visible_if:
                cond_f, cond_v = next(iter(field.visible_if.items()))
                actual_raw = row.get(cond_f) if isinstance(row, dict) else None
                actual = actual_raw.get("value") if isinstance(actual_raw, dict) else actual_raw
                if actual != cond_v:
                    continue
            raw = row.get(field.id) if isinstance(row, dict) else None
            is_empty = (
                raw is None
                or (isinstance(raw, dict) and raw.get("value") is None)
                or (isinstance(raw, dict) and isinstance(raw.get("value"), str) and not raw["value"].strip())
                or (isinstance(raw, dict) and isinstance(raw.get("value"), list) and not raw["value"])
            )
            if is_empty:
                return {"section_id": section.id, "field_id": field.id, "label": field.label}
    return None


def _render_pending_validation_errors(errors: list[dict]) -> str:
    """Render the PENDING_VALIDATION_ERRORS block, or return empty string."""
    if not errors:
        return ""
    lines = [
        "PENDING VALIDATION ERRORS (re-ask — the server rejected the previous answer):"
    ]
    for e in errors:
        ri = e.get("repeatable_index")
        loc = f"{e['section_id']}.{e['field_id']}" + (f"[{ri}]" if ri is not None else "")
        lines.append(f"  - {loc}: {e['reason_human']}  [code: {e['code']}]")
    return "\n".join(lines)


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
        "next_required_field": _compute_next_required_field(schema, state),
        "next_optional_field": _next_optional_field(schema, state),
        "pending_validation_errors": getattr(state, "pending_validation_errors", []),
        "focused_section": getattr(state, "focused_section", None),
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
    cross_screen_text: str | None = None,
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
      __PARTICIPANT_NAME__   — display name for top-level greeting directive
                                (falls back to "unknown" when not set)
      __NEXT_OPTIONAL_FIELD__ — next unfilled optional field in schema order
                                (empty string when all optionals filled)

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

    # Cross-screen summary block — rendered between LIVE_STATE_JSON and the
    # SCHEMA. Hidden entirely when the participant has no prior steps so the
    # first screen of an onboarding journey doesn't carry a stub heading.
    cross_screen_block = (
        f"\n\n{cross_screen_text}" if (cross_screen_text and cross_screen_text.strip()) else ""
    )
    if cross_screen_block:
        # PII-aware diagnostic: this is the ONE log line that intentionally
        # samples the prompt body (first 80 chars). The whole purpose is
        # cross-screen-leak audit — without seeing the prefix we cannot tell
        # whether the right participant's data was injected. DO NOT copy
        # this log pattern into other handlers without a similar audit need.
        log.info(
            "cross_screen_block_injected",
            session_id=state.session_id,
            tenant_id=state.tenant_id,
            participant_id=state.participant_id,
            chars=len(cross_screen_block),
            first_80=cross_screen_block[:80].replace("\n", " "),
        )

    next_req = _compute_next_required_field(schema, state)
    next_req_text = (
        f"{next_req['section_id']}.{next_req['field_id']} ({next_req['label']})"
        if next_req else ""
    )
    pending_errors_text = _render_pending_validation_errors(
        getattr(state, "pending_validation_errors", [])
    )

    # AP-3 fix: surface participant name as a top-level directive token.
    # Previously buried in [LIVE_STATE_JSON] JSON data — model treated it as
    # data, not a greeting directive, causing personalisation to drop on new screens.
    participant_name = (
        bootstrap.participant_display_name
        if bootstrap and bootstrap.participant_display_name
        else "unknown"
    )

    # AP-2 fix: Rule-5 anchor. Gives the model a deterministic next-optional
    # pointer so it iterates optional fields in schema order, not randomly.
    next_opt = _next_optional_field(schema, state)
    next_opt_text = (
        f"{next_opt['section_id']}.{next_opt['field_id']} ({next_opt['label']})"
        if next_opt else ""
    )

    result = (
        template
        .replace("__STEP_LABEL__", schema.step_label)
        .replace("__PROGRESS_PCT__", str(schema.progress_percent))
        .replace("__SCHEMA_JSON__", schema_json)
        .replace("__STATE_JSON__", state_json)
        .replace("__LIVE_STATE_JSON__", live_state_json)
        .replace("__CROSS_SCREEN_SUMMARY__", cross_screen_block)
        .replace("__BOOTSTRAP_MODE__", bootstrap_mode)
        .replace("__GROUNDING_SECTION__", grounding_section)
        .replace("__VOICE_COVERAGE_SECTION__", voice_coverage_section)
        .replace("__NEXT_REQUIRED_FIELD__", next_req_text)
        .replace("__PENDING_VALIDATION_ERRORS__", pending_errors_text)
        .replace("__PARTICIPANT_NAME__", participant_name)
        .replace("__NEXT_OPTIONAL_FIELD__", next_opt_text)
    )

    if resume_context_text:
        result += f"\n\nRESUME CONTEXT\n{resume_context_text}"

    if screen_context_text:
        result += f"\n\nSCREEN CONTEXT\n{screen_context_text}"

    return result
