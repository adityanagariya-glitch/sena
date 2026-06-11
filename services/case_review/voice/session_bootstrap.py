"""Session bootstrap envelope for the case-note voice assistant."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionBootstrap(BaseModel):
    """Canonical session-creation envelope rendered into [LIVE_STATE_JSON]."""

    model_config = {"extra": "ignore"}

    mode: Literal["new_user", "returning_same_page", "page_handoff"] = "new_user"
    # Values pre-filled on this form (from /draft or manual entry).
    # Shape: {section_id: {field_id: value}} or flat {"section.field": value}.
    current_page_values: dict[str, Any] = Field(default_factory=dict)
    # Field paths the agent MUST treat as read-only (identifiers).
    readonly_paths: list[str] = Field(default_factory=list)
    prior_pages: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Worker display name for greeting.
    participant_display_name: str | None = None

    @classmethod
    def from_initial_values(
        cls,
        initial_values: dict[str, Any] | None,
        *,
        readonly_paths: list[str] | None = None,
        worker_display_name: str | None = None,
    ) -> "SessionBootstrap":
        if not initial_values:
            return cls(
                mode="new_user",
                readonly_paths=readonly_paths or [],
                participant_display_name=worker_display_name,
            )
        return cls(
            mode="returning_same_page",
            current_page_values=initial_values,
            readonly_paths=readonly_paths or [],
            participant_display_name=worker_display_name,
        )
