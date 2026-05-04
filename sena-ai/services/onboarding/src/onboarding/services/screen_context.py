"""
Screen state context injection — v2 (screen_state_v2 + v1 adapter).

Pure module (no IO). Accepts v2 ScreenStateV2 payloads directly, or v1
ScreenStateMessage payloads via from_v1() adapter. Renders a deterministic
multi-line [SCREEN] block injected into Gemini as a text turn. payload_hash()
provides idempotency deduplication so unchanged frames are dropped.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ─── v1 models (kept for adapter — one release window) ───────────────────────

class ScreenData(BaseModel):
    """Validated contents of a v1 screen_state data payload. Unknown keys ignored."""

    model_config = {"extra": "ignore"}

    current_screen: str | None = Field(default=None, max_length=64)
    visible_fields: list[str] | None = Field(default=None)
    prefilled: dict[str, Any] | None = None
    app_context: str | None = Field(default=None, max_length=256)

    @field_validator("visible_fields")
    @classmethod
    def _cap_fields(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) > 32:
            raise ValueError("visible_fields exceeds 32 entries")
        return v


class ScreenStateMessage(BaseModel):
    """Top-level v1 screen_state WS message wrapper."""

    model_config = {"extra": "ignore"}

    type: str
    data: ScreenData


# ─── v2 models ───────────────────────────────────────────────────────────────

class ScreenStateV2(BaseModel):
    """
    Structured screen state emitted by Flutter on each field focus change.
    Drives Gemini's awareness of exactly what the user is looking at.
    """

    model_config = {"extra": "ignore"}

    step_id: str | None = None
    focused_section: str | None = None
    focused_field: str | None = None
    # dotted_path → "filled" | "empty" | "invalid"
    field_status: dict[str, Literal["filled", "empty", "invalid"]] = Field(default_factory=dict)
    # Rule 7 — when Flutter rejects a value as invalid, the human-readable
    # reason goes here keyed by the same dotted path. The render layer surfaces
    # this in parentheses on the "Invalid (re-ask)" line so Gemini can
    # paraphrase the reason as a hint to the user.
    field_errors: dict[str, str] = Field(default_factory=dict)
    # section_id → current row count for repeatable sections
    repeatable_rows: dict[str, int] = Field(default_factory=dict)
    ui_flags: dict[str, Any] = Field(default_factory=dict)


class ScreenStateV2Message(BaseModel):
    """Top-level screen_state_v2 WS message wrapper."""

    model_config = {"extra": "ignore"}

    type: str
    data: ScreenStateV2


# ─── v1 → v2 adapter ─────────────────────────────────────────────────────────

def from_v1(msg: ScreenStateMessage, *, session_step_id: str | None = None) -> ScreenStateV2:
    """
    Normalise a v1 ScreenStateMessage into ScreenStateV2.
    Maps current_screen → focused_section. Prefilled keys → "filled" in field_status.
    Visible but not prefilled fields → "empty".
    """
    d = msg.data
    field_status: dict[str, Literal["filled", "empty", "invalid"]] = {}

    section = d.current_screen or ""

    if d.visible_fields:
        for f in d.visible_fields:
            path = f"{section}.{f}" if section else f
            field_status[path] = "empty"

    if d.prefilled:
        for k, v in d.prefilled.items():
            path = f"{section}.{k}" if section else k
            if v is not None and v != "":
                field_status[path] = "filled"
            else:
                field_status[path] = "empty"

    return ScreenStateV2(
        step_id=session_step_id,
        focused_section=section or None,
        focused_field=None,
        field_status=field_status,
        repeatable_rows={},
        ui_flags={"source": "v1_adapter", "app_context": d.app_context},
    )


# ─── rendering ───────────────────────────────────────────────────────────────

def render_injection_text(state: ScreenStateV2) -> str:
    """
    Produce the deterministic multi-line [SCREEN] block injected into Gemini.

    Example output:
        [SCREEN]
        Step: personal_information
        Focus: basics / full_name
        Filled: basics.full_name, basics.email
        Empty: basics.date_of_birth, basics.phone, basics.about_me
        Invalid (re-ask): basics.phone
        Rows: ndis_goals=2
        Flags: show_interpreter_fields=true
    """
    lines: list[str] = ["[SCREEN]"]

    if state.step_id:
        lines.append(f"Step: {state.step_id}")

    focus_parts = [p for p in [state.focused_section, state.focused_field] if p]
    if focus_parts:
        lines.append("Focus: " + " / ".join(focus_parts))

    filled = [p for p, s in state.field_status.items() if s == "filled"]
    empty = [p for p, s in state.field_status.items() if s == "empty"]
    invalid = [p for p, s in state.field_status.items() if s == "invalid"]

    if filled:
        lines.append("Filled: " + ", ".join(sorted(filled)))
    if empty:
        lines.append("Empty: " + ", ".join(sorted(empty)))
    if invalid:
        # Rule 7 — surface frontend-validation reasons inline so the agent can
        # paraphrase them as a hint when re-asking. "phone (Must be 10 digits)"
        # rather than just "phone".
        parts: list[str] = []
        for path in sorted(invalid):
            reason = state.field_errors.get(path)
            if reason:
                parts.append(f"{path} ({reason})")
            else:
                parts.append(path)
        lines.append("Invalid (re-ask): " + ", ".join(parts))

    if state.repeatable_rows:
        rows_str = ", ".join(f"{k}={v}" for k, v in state.repeatable_rows.items())
        lines.append(f"Rows: {rows_str}")

    if state.ui_flags:
        flags_str = ", ".join(
            f"{k}={str(v).lower() if isinstance(v, bool) else v}"
            for k, v in state.ui_flags.items()
            if k != "source"
        )
        if flags_str:
            lines.append(f"Flags: {flags_str}")

    return "\n".join(lines)


# ─── idempotency ─────────────────────────────────────────────────────────────

def payload_hash(data: dict[str, Any]) -> str:
    """
    Stable SHA-256 hash of a payload dict for idempotency deduplication.
    Identical consecutive screen_state payloads produce the same hash so
    the WS handler can drop them without re-injecting into Gemini.
    """
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
