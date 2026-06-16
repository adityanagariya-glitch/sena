"""
Builds the Gemini system instruction for a case-note voice session.

Loads the markdown template from prompts/case_note_system.md and substitutes
session-specific values using explicit string replacement — NOT str.format() —
to avoid conflicts with JSON curly braces inside the schema/state payloads.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from voice.schema_spec import StepSchema
from voice.session_bootstrap import SessionBootstrap
from voice.state import CaseNoteVoiceState as FormState
from voice.validators.sequencing import next_optional_field as _next_optional_field
from voice.validators.sequencing import section_min_unmet as _section_min_unmet  # noqa: F401

log = structlog.get_logger(__name__)
_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "case_note_system.md"


def _render_schema_filtering_hidden_fields(
    schema: StepSchema,
    state: FormState,
    *,
    screen_field_status: dict[str, str] | None = None,
) -> str:
    """Serialize the schema to JSON, dropping fields the worker cannot see now."""
    def _normalize_enum(s: object) -> str:
        if s is None:
            return ""
        return str(s).lower().replace("_", "").replace(" ", "").replace("-", "")

    def _evaluate_visible_if(
        visible_if: dict | None, row_values: dict, section_values: dict
    ) -> bool:
        if not visible_if:
            return True
        cond_field, cond_value = next(iter(visible_if.items()))
        actual_raw = row_values.get(cond_field)
        if actual_raw is None:
            actual_raw = section_values.get(cond_field)
        actual = actual_raw.get("value") if isinstance(actual_raw, dict) else actual_raw
        return _normalize_enum(actual) == _normalize_enum(cond_value)

    rendered_paths: set[str] | None = None
    if screen_field_status:
        rendered_paths = set(screen_field_status.keys())

    raw = schema.model_dump(mode="json")
    sections_out = []
    for section_spec in raw.get("sections", []):
        section_id = section_spec.get("id")
        section_state = state.values.get(section_id) or {}
        scalar_ctx = section_state if isinstance(section_state, dict) else {}
        for key in ("fields", "item_fields"):
            if key not in section_spec or section_spec[key] is None:
                continue
            kept = []
            for fld in section_spec[key]:
                if rendered_paths is not None:
                    fid = fld.get("id")
                    direct = f"{section_id}.{fid}"
                    if direct not in rendered_paths:
                        continue
                vis_if = fld.get("visible_if")
                if _evaluate_visible_if(vis_if, scalar_ctx, scalar_ctx):
                    kept.append(fld)
            section_spec[key] = kept
        sections_out.append(section_spec)
    raw["sections"] = sections_out
    return json.dumps(raw, default=str)


def _compute_next_required_field(
    schema: StepSchema,
    state: FormState,
    *,
    screen_field_status: dict[str, str] | None = None,
) -> dict | None:
    """First required empty field in schema order."""
    for section in schema.sections:
        fields = section.fields or []
        sec_vals = state.values.get(section.id) or {}
        row: dict = sec_vals if isinstance(sec_vals, dict) else {}
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
                if screen_field_status is not None:
                    path = f"{section.id}.{field.id}"
                    if screen_field_status.get(path) == "filled":
                        continue
                return {"section_id": section.id, "field_id": field.id, "label": field.label}
    return None


def _render_pending_validation_errors(errors: list[dict]) -> str:
    if not errors:
        return ""
    lines = ["PENDING VALIDATION ERRORS (re-ask — the server rejected the previous answer):"]
    for e in errors:
        loc = f"{e['section_id']}.{e['field_id']}"
        lines.append(f"  - {loc}: {e['reason_human']}  [code: {e['code']}]")
        allowed = e.get("allowed_values")
        if allowed:
            lines.append(f"    Allowed values: {', '.join(allowed)}")
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


def _partition_state_by_readonly(
    values: dict,
    readonly_paths: list[str],
) -> tuple[dict, dict]:
    if not readonly_paths:
        return {}, values
    readonly_set = set(readonly_paths)
    locked: dict = {}
    askable: dict = {}
    for section_id, section_data in values.items():
        if isinstance(section_data, dict):
            for field_id, fv in section_data.items():
                path = f"{section_id}.{field_id}"
                target = locked if path in readonly_set else askable
                target.setdefault(section_id, {})[field_id] = fv
        else:
            askable[section_id] = section_data
    return locked, askable


def _compute_next_forced_field(schema: StepSchema, state: FormState) -> dict | None:
    forced = getattr(state, "next_forced_field", None)
    if not forced:
        return None
    section_id = forced.get("section")
    field_id = forced.get("field")
    if not section_id or not field_id:
        return None
    label = field_id
    for section in schema.sections:
        if section.id != section_id:
            continue
        for f in (section.fields or []):
            if f.id == field_id:
                label = f.label
        break
    return {"section_id": section_id, "field_id": field_id, "label": label}


def _build_live_state_block(
    bootstrap: SessionBootstrap | None,
    state: FormState,
    schema: StepSchema,
    *,
    screen_field_status: dict[str, str] | None = None,
) -> str:
    completion = state.completion.model_dump() if state.completion else None
    readonly_paths = bootstrap.readonly_paths if bootstrap else []
    locked_facts, askable_state = _partition_state_by_readonly(state.values, readonly_paths)
    next_forced = _compute_next_forced_field(schema, state)
    next_required = next_forced or _compute_next_required_field(
        schema, state, screen_field_status=screen_field_status,
    )
    payload = {
        "mode": (bootstrap.mode if bootstrap else "new_user"),
        "step_id": schema.step_id,
        "step_label": schema.step_label,
        "participant_display_name": (bootstrap.participant_display_name if bootstrap else None),
        "current_page_values": askable_state,
        "locked_facts": locked_facts,
        "readonly_paths": readonly_paths,
        "prior_pages": (bootstrap.prior_pages if bootstrap else {}),
        "completion": completion,
        "next_required_field": next_required,
        "next_forced_field": next_forced,
        "next_optional_field": _next_optional_field(
            schema, state, screen_field_status=screen_field_status,
        ),
        "pending_validation_errors": getattr(state, "pending_validation_errors", []),
        "pending_confirmation": getattr(state, "pending_confirmation", None),
        "focused_section": None,
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
    screen_field_status: dict[str, str] | None = None,
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    schema_json = _render_schema_filtering_hidden_fields(
        schema, state, screen_field_status=screen_field_status,
    )
    state_summary = {
        "values": state.values,
        "completion": state.completion.model_dump() if state.completion else None,
    }
    state_json = json.dumps(state_summary, default=str)

    live_state_json = _build_live_state_block(
        bootstrap, state, schema, screen_field_status=screen_field_status,
    )
    bootstrap_mode = bootstrap.mode if bootstrap else "new_user"

    grounding_section = (
        "\nGROUNDING\n"
        "Google Search is available. Use it only for policy questions you cannot answer from training."
        if grounding_enabled
        else ""
    )

    voice_coverage_section = _voice_coverage_section(schema.voice_coverage)

    cross_screen_block = (
        f"\n\n{cross_screen_text}" if (cross_screen_text and cross_screen_text.strip()) else ""
    )

    next_req = _compute_next_required_field(
        schema, state, screen_field_status=screen_field_status,
    )
    next_req_text = (
        f"{next_req['section_id']}.{next_req['field_id']} ({next_req['label']})"
        if next_req else ""
    )
    pending_errors_text = _render_pending_validation_errors(
        getattr(state, "pending_validation_errors", [])
    )

    worker_name = (
        bootstrap.participant_display_name
        if bootstrap and bootstrap.participant_display_name
        else "unknown"
    )

    next_opt = _next_optional_field(
        schema, state, screen_field_status=screen_field_status,
    )
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
        .replace("__PARTICIPANT_NAME__", worker_name)
        .replace("__NEXT_OPTIONAL_FIELD__", next_opt_text)
        .replace("__VALIDATOR_REMINDER__", "")
    )

    if resume_context_text:
        result += f"\n\nRESUME CONTEXT\n{resume_context_text}"

    if screen_context_text:
        result += f"\n\nSCREEN CONTEXT\n{screen_context_text}"

    return result
