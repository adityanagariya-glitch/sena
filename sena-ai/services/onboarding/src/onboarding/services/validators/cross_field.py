"""Cross-field invariant validators — pure functions, no I/O."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from .base import ValidationRejection

_STRIP_NON_DIGIT = re.compile(r"\D")


def _fv(raw: Any) -> Any:
    """Extract .value from FieldValue dict; return raw otherwise."""
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _s(raw: Any) -> str:
    v = _fv(raw)
    return (v or "").strip() if isinstance(v, str) else ""


def check_emergency_email_unique_and_differs_from_client(
    state_values: dict[str, Any],
) -> list[ValidationRejection]:
    rejections: list[ValidationRejection] = []
    client_email = _s((state_values.get("basics") or {}).get("email")).lower()
    rows = state_values.get("emergency_contacts") or []
    if not isinstance(rows, list):
        return rejections
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        email = _s(row.get("email")).lower()
        if not email:
            continue
        if client_email and email == client_email:
            rejections.append(ValidationRejection(
                code="emergency_email_matches_client",
                reason_human="Emergency contact email must be different from your own email.",
                suggested_fix="Use a different email address for this emergency contact.",
            ))
        if email in seen:
            rejections.append(ValidationRejection(
                code="emergency_email_duplicate",
                reason_human="Each emergency contact must have a unique email address.",
                suggested_fix="Use a different email for this emergency contact.",
            ))
        seen.add(email)
    return rejections


def check_plan_end_after_start(state_values: dict[str, Any]) -> list[ValidationRejection]:
    plan = state_values.get("plan_info") or {}
    start_raw = _s(plan.get("plan_start"))
    end_raw = _s(plan.get("plan_end"))
    if not start_raw or not end_raw:
        return []
    try:
        if date.fromisoformat(end_raw) <= date.fromisoformat(start_raw):
            return [ValidationRejection(
                code="plan_end_not_after_start",
                reason_human="Date must be after start date",
                suggested_fix="Plan end date must be later than the plan start date.",
            )]
    except ValueError:
        pass
    return []


def check_medical_history_all_or_none(state_values: dict[str, Any]) -> list[ValidationRejection]:
    rows = state_values.get("medical_history") or []
    if not isinstance(rows, list):
        return []
    rejections: list[ValidationRejection] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        filled = [f for f in [_s(row.get("title")), _s(row.get("year")), _s(row.get("description"))] if f]
        if 0 < len(filled) < 3:
            rejections.append(ValidationRejection(
                code="medical_history_incomplete_row",
                reason_human="This field is required.",
                suggested_fix=f"Complete all three fields in medical history row {idx + 1}.",
            ))
    return rejections


def check_time_slot_no_overlap(slots: list[dict[str, Any]]) -> list[ValidationRejection]:
    def hm(s: str) -> int | None:
        m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", (s or "").strip())
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None

    parsed: list[tuple[int, int]] = []
    for slot in slots:
        start = hm(_s(slot.get("start_time")))
        end = hm(_s(slot.get("end_time")))
        if start is None or end is None:
            continue
        if end <= start:
            return [ValidationRejection(code="time_slot_end_before_start", reason_human="Start time must be before end time")]
        parsed.append((start, end))
    parsed.sort()
    for i in range(len(parsed) - 1):
        if parsed[i + 1][0] < parsed[i][1]:
            return [ValidationRejection(code="time_slots_overlap", reason_human="Time slots must not overlap")]
    return []


def validate_cross_fields(state_values: dict[str, Any]) -> list[ValidationRejection]:
    results: list[ValidationRejection] = []
    results.extend(check_emergency_email_unique_and_differs_from_client(state_values))
    results.extend(check_plan_end_after_start(state_values))
    results.extend(check_medical_history_all_or_none(state_values))
    return results
