"""
Cross-screen shared-context — pure module.

Single source of truth for what a "step summary" looks like, how a completed
FormState's values get split into verbatim and compressed buckets, how the
compression encodes (key alias map) and decodes (round-trippable), and how a
list of summaries renders into the natural-language prompt block.

Stateless. No I/O. No Redis. No Pydantic side-effects. Driven by hand-tuned
constant tables; everything else is internal helpers.

Public interface (everything else is `_private`):
    KEY_ALIASES                    — verbatim/compressed split and aliasing
    VERBATIM_FIELDS                — the six high-signal field names
    build_summary(form_state, ...) → StepSummary
    compress_residual(form_state, exclude_keys) → str
    decompress(s)                  → dict
    render_for_prompt(summaries, now) → str

Tested in tests/test_cross_screen_context.py — round-trip property test,
verbatim passthrough, empty FormState, render snapshot, token-budget smoke.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from onboarding.models.cross_screen_summary import CrossScreenContext, StepSummary
from onboarding.models.form_state import FormState

# ── Public constants ─────────────────────────────────────────────────────────

#: Field names whose values pass through to the summary unchanged. These were
#: chosen by the product owner because they are the highest-signal fields for
#: warmth and conversational continuity. Adding to this set requires a PRD
#: update and a refreshed render-snapshot test — not an inline change.
VERBATIM_FIELDS: frozenset[str] = frozenset({
    "name",
    "dob",
    "gender",
    "goals",
    "hobbies",
    "interests",
})

#: Deterministic short alias for residual (compressed) field keys. Stable
#: across builds; new fields the table doesn't know about fall back to a
#: deterministic three-letter abbreviation derived from the last path segment
#: (see `_fallback_alias`). The two-way map enables byte-equivalent
#: round-tripping under `decompress`.
KEY_ALIASES: dict[str, str] = {
    "basics": "bsc",
    "address": "addr",
    "phone": "ph",
    "email": "em",
    "emergency_contacts": "ec",
    "cultural_requirements": "cr",
    "communication_preferences": "cp",
    "medical_history": "mh",
    "medications": "med",
    "allergies": "alg",
    "diagnoses": "dx",
    "allied_health": "ah",
    "ndis_number": "nn",
    "ndis_plan_start": "nps",
    "ndis_plan_end": "npe",
    "plan_management": "pm",
    "funding_left": "fl",
    "ndis_goals": "ng",
    "service_locations": "sl",
    "support_schedule": "ss",
    "morning_routine": "mr",
    "evening_routine": "er",
    "consent": "cn",
    "languages": "lng",
    "support_frequency": "sf",
    "blood_type": "bt",
    "height": "ht",
    "weight": "wt",
}

# Reverse map for decompression. Built once; used inside `decompress`.
_ALIAS_TO_KEY: dict[str, str] = {v: k for k, v in KEY_ALIASES.items()}

# Cap on how many recent steps render verbatim in the prompt block. Older steps
# render only as their compressed line so the prompt cannot grow unbounded
# when a participant has many completed steps.
_VERBATIM_INLINE_CAP = 5


# ── Public API ───────────────────────────────────────────────────────────────


def build_summary(
    form_state: FormState,
    *,
    step_number: int,
    step_label: str,
    completed_at: datetime | None = None,
) -> StepSummary:
    """Distil a completed FormState into a StepSummary.

    `form_state.values` is the canonical FormState shape: section_id →
    {field_id: FieldValue.model_dump} OR section_id → list[{...}] for
    repeatable sections. Verbatim fields are extracted (matched on field_id at
    any nesting depth — top-level OR inside a section). Everything else flows
    into `compress_residual` losslessly.
    """
    flat = _flatten_populated(form_state.values)

    verbatim: dict[str, Any] = {}
    seen_verbatim_paths: set[str] = set()
    for path, value in flat.items():
        leaf = path.rsplit(".", 1)[-1]
        if leaf in VERBATIM_FIELDS and leaf not in verbatim:
            verbatim[leaf] = value
            seen_verbatim_paths.add(path)

    compressed = compress_residual(form_state, exclude_keys=seen_verbatim_paths)

    completion_pct = 0.0
    if form_state.completion is not None:
        completion_pct = round(form_state.completion.percent / 100.0, 4)

    return StepSummary(
        step_number=step_number,
        step_label=step_label,
        completed_at=completed_at or datetime.now(timezone.utc),
        session_id=form_state.session_id,
        verbatim=verbatim,
        compressed=compressed,
        completion_pct=completion_pct,
    )


def compress_residual(form_state: FormState, exclude_keys: set[str]) -> str:
    """Compact, lossless JSON of every populated FormState field not excluded.

    Encoding rules:
      1. Drop fields whose flattened path is in ``exclude_keys`` (used by
         ``build_summary`` to remove already-verbatim leaves).
      2. Build a `{alias: value}` mapping by replacing each top-level section
         key with its alias from ``KEY_ALIASES`` (or a deterministic fallback
         from `_fallback_alias`). Values are passed through unchanged for
         scalar sections; nested section payloads are serialised whole so
         field-level keys are preserved on the inside (this stays
         round-trippable because the alias only rewrites the outermost key).
      3. Drop None and empty containers.
      4. Emit compact JSON (no whitespace, sorted keys).

    `decompress(s)` reverses step 2 to recover the original section keys.
    """
    sections_kept: dict[str, Any] = {}
    for section_id, section_data in form_state.values.items():
        section_payload = _strip_section(
            section_id, section_data, exclude_keys=exclude_keys,
        )
        if _is_meaningful(section_payload):
            sections_kept[section_id] = section_payload

    aliased: dict[str, Any] = {}
    for section_id, payload in sections_kept.items():
        alias = KEY_ALIASES.get(section_id) or _fallback_alias(section_id)
        # Disambiguation — if two original keys collapse to the same alias,
        # keep the one whose original key sorts first (deterministic).
        if alias in aliased:
            aliased[alias + "_" + section_id[:2]] = payload
        else:
            aliased[alias] = payload

    if not aliased:
        return ""
    return json.dumps(aliased, separators=(",", ":"), sort_keys=True, default=str)


def decompress(s: str) -> dict[str, Any]:
    """Inverse of `compress_residual` for the section-key-alias dimension.

    Round-trips the encoded JSON back to its original shape modulo:
      - Key ordering inside nested dicts (we re-emit sorted keys).
      - Aliases for which there is no entry in ``_ALIAS_TO_KEY`` — those keys
        come back as their alias form. The fallback-alias rule guarantees that
        for any input that round-trips through `compress_residual`, the
        decoded payload is byte-equivalent to the encoded one when re-encoded
        with `json.dumps(..., sort_keys=True)`.

    The lossless-guarantee property test in
    ``tests/test_cross_screen_context.py`` codifies this invariant.
    """
    if not s:
        return {}
    decoded = json.loads(s)
    out: dict[str, Any] = {}
    for alias, payload in decoded.items():
        original = _ALIAS_TO_KEY.get(alias, alias)
        out[original] = payload
    return out


def render_for_prompt(
    bucket: CrossScreenContext | list[StepSummary],
    *,
    now: datetime | None = None,
) -> str:
    """Render the cross-screen context as a readable prompt block.

    Returns the empty string when the bucket is empty so that
    ``prompt_builder`` can no-op the placeholder. The block is deliberately
    narrative (not a JSON dump) — Gemini Live treats narrative system context
    better than nested JSON for tone purposes.
    """
    summaries = bucket.summaries if isinstance(bucket, CrossScreenContext) else list(bucket)
    if not summaries:
        return ""

    now = now or datetime.now(timezone.utc)
    summaries_sorted = sorted(summaries, key=lambda s: s.step_number)
    inline_cutoff = max(0, len(summaries_sorted) - _VERBATIM_INLINE_CAP)

    lines: list[str] = [
        "EARLIER IN THIS ONBOARDING (do not re-ask, reference naturally if relevant)",
        "",
    ]
    for idx, s in enumerate(summaries_sorted):
        ago = _format_time_since(s.completed_at, now)
        header = f"Step {s.step_number} — {s.step_label} (completed {ago}):"
        lines.append(header)
        if idx < inline_cutoff:
            # Older than the verbatim-inline cap → collapse to compressed only.
            if s.compressed:
                lines.append(f"  Captured (compressed): {s.compressed}")
        else:
            verbatim_line = _format_verbatim(s.verbatim)
            if verbatim_line:
                lines.append("  " + verbatim_line)
            if s.compressed:
                lines.append(f"  Other captured (compressed): {s.compressed}")
        lines.append("")

    # Drop trailing blank.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


# ── Internal helpers ─────────────────────────────────────────────────────────


def _flatten_populated(values: dict[str, Any]) -> dict[str, Any]:
    """Walk FormState.values once and emit ``{section.field: raw_value}``.

    Skips None / empty entries. Repeatable sections expand to
    ``section[idx].field``; non-FieldValue dicts (legacy shapes) are tolerated.
    """
    out: dict[str, Any] = {}
    for section_id, section_data in values.items():
        if isinstance(section_data, list):
            for idx, row in enumerate(section_data):
                if not isinstance(row, dict):
                    continue
                for field_id, fv in row.items():
                    raw = _unwrap_field_value(fv)
                    if raw is not None:
                        out[f"{section_id}[{idx}].{field_id}"] = raw
        elif isinstance(section_data, dict):
            for field_id, fv in section_data.items():
                raw = _unwrap_field_value(fv)
                if raw is not None:
                    out[f"{section_id}.{field_id}"] = raw
    return out


def _unwrap_field_value(fv: Any) -> Any:
    """FieldValue.model_dump() shapes carry the actual value under "value".

    Pre-FieldValue legacy shapes (a bare scalar or list) are returned as-is.
    Empty strings and empty containers count as "not populated" → return None.
    """
    if isinstance(fv, dict) and "value" in fv:
        v = fv.get("value")
    else:
        v = fv
    if v is None:
        return None
    if isinstance(v, str) and v == "":
        return None
    if isinstance(v, (list, dict)) and len(v) == 0:
        return None
    return v


def _strip_section(
    section_id: str,
    section_data: Any,
    *,
    exclude_keys: set[str],
) -> Any:
    """Return a copy of ``section_data`` with excluded fields removed.

    Handles both flat ``{field: FieldValue}`` and repeatable
    ``[{field: FieldValue}, ...]`` shapes. Field values are unwrapped to their
    raw scalar/list/dict so the encoded JSON is compact.
    """
    if isinstance(section_data, list):
        rows: list[dict[str, Any]] = []
        for idx, row in enumerate(section_data):
            if not isinstance(row, dict):
                continue
            kept_row: dict[str, Any] = {}
            for field_id, fv in row.items():
                path = f"{section_id}[{idx}].{field_id}"
                if path in exclude_keys:
                    continue
                raw = _unwrap_field_value(fv)
                if raw is not None:
                    kept_row[field_id] = raw
            if kept_row:
                rows.append(kept_row)
        return rows
    if isinstance(section_data, dict):
        kept: dict[str, Any] = {}
        for field_id, fv in section_data.items():
            path = f"{section_id}.{field_id}"
            if path in exclude_keys:
                continue
            raw = _unwrap_field_value(fv)
            if raw is not None:
                kept[field_id] = raw
        return kept
    return None


def _is_meaningful(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, (list, dict)):
        return len(payload) > 0
    return True


def _fallback_alias(key: str) -> str:
    """Deterministic three-letter fallback for keys not in `KEY_ALIASES`.

    Uses the last path segment, lowercased, first three alphanumeric chars.
    Pads with the prefix `x` if the segment is shorter so the result is always
    exactly three characters.
    """
    seg = key.split(".")[-1].lower()
    chars = [c for c in seg if c.isalnum()]
    base = "".join(chars[:3])
    if len(base) < 3:
        base = (base + "xxx")[:3]
    return base


def _format_time_since(completed_at: datetime, now: datetime) -> str:
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = now - completed_at
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hr ago"
    days = hours // 24
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def _format_verbatim(verbatim: dict[str, Any]) -> str:
    if not verbatim:
        return ""
    parts: list[str] = []
    for key in ("name", "dob", "gender"):
        if key in verbatim and verbatim[key] is not None:
            parts.append(f"{key.capitalize()}: {verbatim[key]}")
    for key in ("goals", "hobbies", "interests"):
        if key in verbatim and verbatim[key]:
            value = verbatim[key]
            if isinstance(value, list):
                rendered = "; ".join(str(v) for v in value)
            else:
                rendered = str(value)
            parts.append(f"{key.capitalize()}: {rendered}")
    return ".  ".join(parts) + "." if parts else ""
