"""
Screen state context injection — Phase D-replacement.

Pure module (no IO). Validates incoming screen_state WS messages,
renders them into a deterministic [SCREEN] injection text for Gemini,
and provides a stable hash for idempotency deduplication so identical
consecutive frames are dropped without re-injecting.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ScreenData(BaseModel):
    """Validated contents of a screen_state data payload. Unknown keys ignored."""

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
    """Top-level screen_state WS message wrapper."""

    model_config = {"extra": "ignore"}

    type: str
    data: ScreenData


def render_injection_text(msg: ScreenStateMessage) -> str:
    """
    Produce the deterministic [SCREEN] line injected into Gemini as a text turn.

    Example:
        [SCREEN] section=personal_information; visible=full_name,date_of_birth;
        prefilled={full_name=John Smith}; note="user is on step 1 of 5".
    """
    d = msg.data
    parts: list[str] = []

    if d.current_screen:
        parts.append(f"section={d.current_screen}")
    if d.visible_fields:
        parts.append(f"visible={','.join(d.visible_fields)}")
    if d.prefilled:
        items = "; ".join(f"{k}={v}" for k, v in d.prefilled.items())
        parts.append(f"prefilled={{{items}}}")
    if d.app_context:
        parts.append(f'note="{d.app_context}"')

    return "[SCREEN] " + "; ".join(parts) + "."


def payload_hash(data: dict[str, Any]) -> str:
    """
    Stable SHA-256 hash of a payload dict for idempotency deduplication.
    Identical consecutive screen_state payloads produce the same hash so
    the WS handler can drop them without re-injecting into Gemini.
    """
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
