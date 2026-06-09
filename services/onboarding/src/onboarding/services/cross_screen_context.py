"""
Cross-screen shared-context — pure module.

A completed step's FormState is distilled into a `StepSummary` that contains
ONLY a tightly-curated allowlist of high-signal fields (name, DOB, gender,
goals, hobbies & interests, plus the care-critical medical facts primary
diagnosis, blood type and allergies). Everything else — phone, email,
addresses, plan details, medications, full medical history — stays scoped to
the step that captured it.

The previous implementation passed a lossless compressed JSON of every
non-allowlisted field across steps too. That worked but produced noisy
prompts and led to the agent confusing the participant's name with an
emergency-contact name (leaf-only matching collided on the bare "name"
field-id). This module's allowlist is explicitly keyed by (section, field)
so that mismatch cannot recur.

Stateless. No I/O. No Redis. Driven by the `ALLOWLIST_PATHS` constant.

Public interface (everything else is `_private`):
    ALLOWLIST_PATHS                     — (section, field) → verbatim key
    build_summary(form_state, ...)      → StepSummary
    render_for_prompt(summaries, now)   → str
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from onboarding.models.cross_screen_summary import CrossScreenContext, StepSummary
from sena_common.voice.form_state import FormState

# ── Public constants ─────────────────────────────────────────────────────────

#: Hard allowlist for cross-screen context. Maps a schema (section_id,
#: field_id) pair to the verbatim concept key used in the rendered prompt
#: block. Repeatable sections (where the same pair appears in multiple rows)
#: collect their values into a list under the verbatim key.
#:
#: Adding to this set requires a product decision — every extra field becomes
#: extra tokens in every subsequent step's system prompt and incrementally
#: confuses the agent. Kept deliberately small; medical concepts were added
#: 2026-06-04 by product decision (care-critical recall across screens).
ALLOWLIST_PATHS: dict[tuple[str, str], str] = {
    ("basics", "full_name"):                "name",
    ("basics", "date_of_birth"):            "dob",
    ("basics", "gender"):                   "gender",
    ("requirements", "goals"):              "goals",
    ("requirements", "hobbies_interests"):  "hobbies_interests",
    # Repeatable: each ndis_goals row's `goal` is appended to verbatim["goals"].
    ("ndis_goals", "goal"):                 "goals",
    # Medical concepts (Medical step section `summary` + repeatable `allergies`).
    # Product decision 2026-06-04: carry the most care-critical facts across
    # screens so the agent never re-asks them. This intentionally widens the
    # earlier step-scoped boundary for medical data.
    ("summary", "primary_diagnosis"):       "diagnosis",
    ("summary", "blood_type"):              "blood_type",
    # Repeatable: each allergies row's `title` is appended to verbatim["allergies"].
    ("allergies", "title"):                 "allergies",
}

# Cap on how many recent steps render in the prompt block. Keeps the system
# prompt bounded even when a participant has many completed steps.
_RENDER_CAP = 5


# ── Public API ───────────────────────────────────────────────────────────────


def build_summary(
    form_state: FormState,
    *,
    step_number: int,
    step_label: str,
    completed_at: datetime | None = None,
) -> StepSummary:
    """Distil a completed FormState into a StepSummary.

    Only fields whose (section_id, field_id) appears in ``ALLOWLIST_PATHS``
    are extracted. The resulting ``verbatim`` dict is keyed by concept name
    (e.g. "name", "goals"), not the raw field path — this also means
    `emergency_contacts[*].name` cannot be misread as the participant's name.
    """
    verbatim: dict[str, Any] = {}
    for section_id, section_data in form_state.values.items():
        if isinstance(section_data, list):
            for row in section_data:
                if not isinstance(row, dict):
                    continue
                for field_id, fv in row.items():
                    key = ALLOWLIST_PATHS.get((section_id, field_id))
                    if key is None:
                        continue
                    raw = _unwrap(fv)
                    if raw is None:
                        continue
                    _append_repeatable(verbatim, key, raw)
        elif isinstance(section_data, dict):
            for field_id, fv in section_data.items():
                key = ALLOWLIST_PATHS.get((section_id, field_id))
                if key is None:
                    continue
                raw = _unwrap(fv)
                if raw is None:
                    continue
                if key not in verbatim:
                    verbatim[key] = raw

    completion_pct = 0.0
    if form_state.completion is not None:
        completion_pct = round(form_state.completion.percent / 100.0, 4)

    return StepSummary(
        step_number=step_number,
        step_label=step_label,
        completed_at=completed_at or datetime.now(UTC),
        session_id=form_state.session_id,
        verbatim=verbatim,
        # Cross-screen context no longer carries compressed residual.
        compressed="",
        completion_pct=completion_pct,
    )


def render_for_prompt(
    bucket: CrossScreenContext | list[StepSummary],
    *,
    now: datetime | None = None,
) -> str:
    """Render the cross-screen context as a readable prompt block.

    Returns the empty string when the bucket is empty so ``prompt_builder``
    can no-op the placeholder. Narrative format — Gemini Live treats prose
    better than JSON for tone.
    """
    summaries = (
        bucket.summaries if isinstance(bucket, CrossScreenContext) else list(bucket)
    )
    if not summaries:
        return ""

    now = now or datetime.now(UTC)
    summaries_sorted = sorted(summaries, key=lambda s: s.step_number)[-_RENDER_CAP:]

    lines: list[str] = [
        "EARLIER IN THIS ONBOARDING (do not re-ask, reference naturally if relevant)",
        "",
    ]
    for s in summaries_sorted:
        ago = _format_time_since(s.completed_at, now)
        lines.append(f"Step {s.step_number} — {s.step_label} (completed {ago}):")
        verbatim_line = _format_verbatim(s.verbatim)
        if verbatim_line:
            lines.append("  " + verbatim_line)
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


# ── Internal helpers ─────────────────────────────────────────────────────────


def _unwrap(fv: Any) -> Any:
    """Pull the raw value out of a FieldValue dump.

    Legacy shapes (bare scalar/list) are returned as-is. Empty strings and
    empty containers count as "not populated" → return None.
    """
    v = fv.get("value") if isinstance(fv, dict) and "value" in fv else fv
    if v is None:
        return None
    if isinstance(v, str) and v == "":
        return None
    if isinstance(v, (list, dict)) and len(v) == 0:
        return None
    return v


def _append_repeatable(verbatim: dict[str, Any], key: str, raw: Any) -> None:
    existing = verbatim.get(key)
    if isinstance(existing, list):
        existing.append(raw)
    elif existing is not None:
        verbatim[key] = [existing, raw]
    else:
        verbatim[key] = [raw]


def _format_time_since(completed_at: datetime, now: datetime) -> str:
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
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
        if verbatim.get(key) is not None:
            parts.append(f"{key.capitalize()}: {verbatim[key]}")
    if verbatim.get("goals"):
        value = verbatim["goals"]
        rendered = "; ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        parts.append(f"Goals: {rendered}")
    if verbatim.get("hobbies_interests"):
        value = verbatim["hobbies_interests"]
        rendered = "; ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        parts.append(f"Hobbies & interests: {rendered}")
    for key, label in (("diagnosis", "Diagnosis"), ("blood_type", "Blood type")):
        if verbatim.get(key) is not None:
            parts.append(f"{label}: {verbatim[key]}")
    if verbatim.get("allergies"):
        value = verbatim["allergies"]
        rendered = "; ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        parts.append(f"Allergies: {rendered}")
    return ".  ".join(parts) + "." if parts else ""
