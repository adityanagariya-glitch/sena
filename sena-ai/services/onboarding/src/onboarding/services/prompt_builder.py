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
from datetime import date, timedelta
from pathlib import Path

import structlog

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import StepSchema
from onboarding.models.session_bootstrap import SessionBootstrap
from onboarding.services.validators.sequencing import next_optional_field as _next_optional_field
from onboarding.services.validators.sequencing import section_min_unmet as _section_min_unmet

log = structlog.get_logger(__name__)
_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "onboarding_system.md"


def _render_schema_filtering_hidden_fields(
    schema: StepSchema,
    state: FormState,
    *,
    screen_field_status: dict[str, str] | None = None,
) -> str:
    """Serialize the schema to JSON for the prompt, dropping fields the
    user cannot see on their screen RIGHT NOW.

    Two filtering layers (in order of authority):

    1. **Flutter screen state** — when `screen_field_status` is provided
       (a dict of `section.field` paths Flutter has rendered), it is the
       AUTHORITATIVE list of askable fields. Any schema field whose dotted
       path is absent from `screen_field_status` is stripped. This is the
       fix for the production "agent asks for plan_manager on a Self
       Managed plan" bug: Flutter only sends `screen_field_status` keys
       for fields it actually renders, so hidden fields are invisible to
       the model regardless of what the schema declares.

    2. **Schema visible_if fallback** — when no screen state has arrived
       (first turn, before Flutter has sent any screen_state_v2 frame),
       evaluate each field's `visible_if` against current state.values
       as a best-effort guard.

    Background (2026-05-19 production regression — session 8431a840):
    Schema fixtures may carry `visible_if`, but the schema sent dynamically
    by Flutter at session-create may not. Layer 1 makes the guard work
    even when the schema is missing visible_if metadata, because Flutter
    just doesn't include hidden fields in screen_field_status.
    """
    def _normalize_enum(s: object) -> str:
        """Canonicalise enum values so display strings ('Plan Managed') and
        wire constants ('PLAN_MANAGED', 'plan_managed') compare equal.
        Bootstrap may deliver values in either form depending on which
        screen/route generates them — normalising here makes visible_if
        robust to both shapes."""
        if s is None:
            return ""
        return str(s).lower().replace("_", "").replace(" ", "").replace("-", "")

    def _evaluate_visible_if(
        visible_if: dict | None, row_values: dict, section_values: dict
    ) -> bool:
        if not visible_if:
            return True
        cond_field, cond_value = next(iter(visible_if.items()))
        # Look up the conditional field value: first in the same row
        # (repeatable item-level visible_if), then in the parent section
        # (scalar field referencing a sibling), then None if neither set.
        actual_raw = row_values.get(cond_field)
        if actual_raw is None:
            actual_raw = section_values.get(cond_field)
        actual = actual_raw.get("value") if isinstance(actual_raw, dict) else actual_raw
        return _normalize_enum(actual) == _normalize_enum(cond_value)

    # Layer 1: Flutter screen state is authoritative when present.
    rendered_paths: set[str] | None = None
    if screen_field_status:
        rendered_paths = set(screen_field_status.keys())

    raw = schema.model_dump(mode="json")
    sections_out = []
    for section_spec in raw.get("sections", []):
        section_id = section_spec.get("id")
        section_state = state.values.get(section_id) or {}
        is_rep = section_spec.get("repeatable") is not None
        # Pick the parent context for visible_if evaluation. For repeatable
        # sections we evaluate against the FIRST row (the agent only asks
        # one row at a time anyway). For scalar sections, the section itself.
        if is_rep:
            row_ctx = (
                section_state[0]
                if isinstance(section_state, list) and section_state
                else {}
            )
            scalar_ctx: dict = row_ctx if isinstance(row_ctx, dict) else {}
        else:
            scalar_ctx = section_state if isinstance(section_state, dict) else {}
        # Filter both fields and item_fields lists.
        for key in ("fields", "item_fields"):
            if key not in section_spec or section_spec[key] is None:
                continue
            kept = []
            for fld in section_spec[key]:
                # Layer 1 — Flutter authoritative: if screen state was
                # provided AND this field's path isn't in the rendered list,
                # drop it. Repeatable item_fields: keep when ANY path
                # `<section>.<idx>.<field>` or `<section>.<field>` appears
                # in screen_field_status (Flutter may key them either way).
                if rendered_paths is not None:
                    fid = fld.get("id")
                    direct = f"{section_id}.{fid}"
                    rep_prefix = f"{section_id}."  # e.g. ndis_goals.0.goal
                    rep_suffix = f".{fid}"
                    in_screen = (
                        direct in rendered_paths
                        or any(
                            p.startswith(rep_prefix) and p.endswith(rep_suffix)
                            for p in rendered_paths
                        )
                    )
                    if not in_screen:
                        continue
                # Layer 2 — visible_if fallback (used on turn 0 before any
                # screen_state_v2 frame arrives).
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
    """First required empty field in schema order — rendered into live-state JSON.

    `screen_field_status` (optional): dot-notation `section.field` → status from
    latest screen_state_v2. Paths marked "filled" are skipped even when state is
    empty — mirrors sequencing.next_required_field. Schema-agnostic.
    """
    for section in schema.sections:
        is_rep = getattr(section, "is_repeatable", False)
        # Optional-repeatable guard (mirror sequencing.next_required_field):
        # for repeatables with min=0 and zero rows, the whole section is
        # skippable — do NOT iterate required item_fields against a
        # synthesised empty row. Otherwise routine sections marked optional
        # would surface a phantom "Routine step" required-field gap.
        if is_rep:
            rep_cfg = getattr(section, "repeatable", None)
            _min_rows = getattr(rep_cfg, "min", 0) if rep_cfg else 0
            _sec_rows = state.values.get(section.id)
            _row_count = len(_sec_rows) if isinstance(_sec_rows, list) else 0
            if _min_rows == 0 and _row_count == 0:
                continue
        fields = section.item_fields if is_rep else (section.fields or [])
        sec_vals = state.values.get(section.id) or {}
        # Section-min gate (V4): if this repeatable section has fewer rows than
        # its declared minimum, surface it as the next required "field" before
        # inspecting any scalar field within it.
        if _section_min_unmet(section, state.values.get(section.id)):
            min_count = section.repeatable.min
            cur_rows = len(state.values.get(section.id) or [])
            return {
                "section_id": section.id,
                "action": "add_repeatable_row",
                "rows_current": cur_rows,
                "rows_min_required": min_count,
                "instruction": (
                    f"Call add_repeatable_row(section_id='{section.id}') to create"
                    f" row {cur_rows + 1}, then fill its fields."
                    " Do NOT call update_field before the row exists."
                ),
            }

        if is_rep:
            row: dict = (sec_vals[0] if isinstance(sec_vals, list) and sec_vals else {})
        else:
            row = (sec_vals if isinstance(sec_vals, dict) else {})
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
                or (
                    isinstance(raw, dict) and isinstance(raw.get("value"), str)
                    and not raw["value"].strip()
                )
                or (
                    isinstance(raw, dict) and isinstance(raw.get("value"), list)
                    and not raw["value"]
                )
            )
            if is_empty:
                # Honor latest screen-state — Flutter is the ground truth for
                # what the user sees on the screen RIGHT NOW. Useful when the
                # FormState hasn't caught up to UI pre-fill yet.
                if screen_field_status is not None:
                    path = f"{section.id}.{field.id}"
                    if screen_field_status.get(path) == "filled":
                        continue
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
        # V3: surface allowed options for enum_invalid so Gemini can re-ask correctly
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
    """M4 — Split state into locked-facts vs askable buckets.

    Readonly fields are NEVER question candidates — they are facts. The agent
    has historically confused "field exists in state AND in readonly_paths"
    for "field is missing but locked", producing the email re-ask loop.
    This split makes that ambiguity structurally impossible.

    Returns (locked_facts, askable_state) — both keyed identically to the
    original `values` (section_id → {field_id: FieldValue dump}).
    """
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
            # Repeatable sections never contain readonly fields (declared at
            # section.field level, not row.field level). Pass through untouched.
            askable[section_id] = section_data
    return locked, askable


def _compute_next_forced_field(
    schema: StepSchema,
    state: FormState,
) -> dict | None:
    """M5 — When the dispatcher set state.next_forced_field, return it
    formatted like _compute_next_required_field. Falls back to None if the
    forced field is already filled (the unlock was satisfied by an earlier
    fill, e.g. via the app surface)."""
    forced = getattr(state, "next_forced_field", None)
    if not forced:
        return None
    section_id = forced.get("section")
    field_id = forced.get("field")
    if not section_id or not field_id:
        return None
    # Look up the label for nicer prompt rendering.
    label = field_id
    for section in schema.sections:
        if section.id != section_id:
            continue
        is_rep = getattr(section, "is_repeatable", False)
        fields = section.item_fields if is_rep else (section.fields or [])
        for f in fields:
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
    """Render the [LIVE_STATE_JSON] context block.

    This block is the SOLE authority for prior conversation context — Gemini is
    instructed in the prompt to treat it that way. Renders bootstrap fields
    (mode, readonly_paths, prior_pages, display_name) plus the live FormState
    partitioned into locked_facts (readonly) and current_page_values (askable),
    plus completion stats.

    `screen_field_status` is forwarded to next_required_field so that a path
    marked "filled" in the latest screen_state_v2 is not surfaced as the next
    question — the agent trusts what Flutter says the user already sees.
    """
    completion = state.completion.model_dump() if state.completion else None
    readonly_paths = bootstrap.readonly_paths if bootstrap else []
    locked_facts, askable_state = _partition_state_by_readonly(
        state.values, readonly_paths,
    )
    # M5 — forced field overrides next_required when set.
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
        "focused_section": getattr(state, "focused_section", None),
    }
    return json.dumps(payload, default=str)


def _build_validator_reminder(state: FormState, schema: StepSchema) -> str:
    """M2 — Per-turn injection of deterministic validator facts.

    The model can't do arithmetic on dates reliably. We do it server-side
    and hand it the exact thresholds. This block sits between the schema
    and the next-required-field line so it's read every turn.
    """
    today = date.today()
    eighteen_years_ago = today - timedelta(days=18 * 365 + 4)  # leap-year padding
    cutoff_str = eighteen_years_ago.isoformat()
    lines = [
        "[VALIDATOR_REMINDER]",
        f"Today is {today.isoformat()}.",
        f"date_of_birth requires age >= 18. Acceptable born-on-or-before: {cutoff_str}.",
        "You MUST call update_field for every captured value — NEVER acknowledge "
        "a value verbally before the server returns {ok: true}.",
        "[/VALIDATOR_REMINDER]",
    ]
    return "\n".join(lines)


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

    # Filter out fields the user cannot currently see on their screen.
    # Layer 1: when Flutter has sent a screen_state_v2 frame, its
    # `screen_field_status` map is the authoritative list of rendered
    # fields — anything absent is hidden. Layer 2: fall back to evaluating
    # the schema's `visible_if` clauses when no screen state has arrived
    # yet. Either way the agent literally cannot see hidden fields in the
    # schema JSON section of the prompt.
    schema_json = _render_schema_filtering_hidden_fields(
        schema, state, screen_field_status=screen_field_status,
    )

    # Compact state snapshot — only what the model needs to skip already-filled fields
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

    next_req = _compute_next_required_field(
        schema, state, screen_field_status=screen_field_status,
    )
    if next_req and next_req.get("action") == "add_repeatable_row":
        next_req_text = (
            f"ACTION_REQUIRED: call add_repeatable_row(section_id='{next_req['section_id']}')"
            f" — {next_req['rows_current']} of {next_req['rows_min_required']} rows exist."
            " Do NOT call update_field until the row exists."
        )
    else:
        next_req_text = (
            f"{next_req['section_id']}.{next_req['field_id']} ({next_req['label']})"
            if next_req else ""
        )
    pending_errors_text = _render_pending_validation_errors(
        getattr(state, "pending_validation_errors", [])
    )
    validator_reminder = _build_validator_reminder(state, schema)

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
    # Honour screen_field_status so hidden optional fields aren't surfaced
    # to the model via this token (Rule 21a anti-leak).
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
        .replace("__PARTICIPANT_NAME__", participant_name)
        .replace("__NEXT_OPTIONAL_FIELD__", next_opt_text)
        .replace("__VALIDATOR_REMINDER__", validator_reminder)
    )

    if resume_context_text:
        result += f"\n\nRESUME CONTEXT\n{resume_context_text}"

    if screen_context_text:
        result += f"\n\nSCREEN CONTEXT\n{screen_context_text}"

    return result
