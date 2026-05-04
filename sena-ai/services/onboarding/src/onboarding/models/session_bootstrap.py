"""
Session bootstrap envelope — declares Rule 1 / Rule 2 hygiene contract.

Every onboarding voice session is created with a bootstrap envelope that tells
the agent EXACTLY which state it inherits and which fields are read-only. The
system prompt renders this as a single [LIVE_STATE_JSON] block; the agent is
instructed to treat it as the ONLY authority for any prior context, so a fresh
session on the same page cannot bleed in conversation memory from a prior run.

Modes:
  - new_user             : Fresh participant, no prior data. Generic greeting.
  - returning_same_page  : Same page, fresh session — agent clears chat memory
                           and treats current_page_values as already-collected.
  - page_handoff         : Multi-step transition — prior_pages contains values
                           from earlier steps; agent acknowledges by name.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionBootstrap(BaseModel):
    """Canonical session-creation envelope rendered into [LIVE_STATE_JSON]."""

    model_config = {"extra": "ignore"}

    mode: Literal["new_user", "returning_same_page", "page_handoff"] = "new_user"
    # Values pre-filled on THIS page. Mirrors what FormState.values is seeded with.
    # Shape: {section_id: {field_id: value}} or flat {"section.field": value}.
    current_page_values: dict[str, Any] = Field(default_factory=dict)
    # Field paths the agent MUST treat as read-only (e.g. ["basics.email"]).
    # update_field calls targeting these paths are rejected by the dispatcher.
    readonly_paths: list[str] = Field(default_factory=list)
    # Values from earlier completed steps, keyed by step_id.
    # Shape: {step_id: {section.field: value}}.
    prior_pages: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Convenience for greeting; when set, the agent addresses the user by name.
    participant_display_name: str | None = None

    @classmethod
    def from_initial_state(cls, initial_state: dict | None) -> "SessionBootstrap":
        """Backwards-compat: synthesise a bootstrap from the legacy initial_state.

        Used when older clients post `initial_state` without an explicit
        `bootstrap` envelope. Defaults to mode=returning_same_page when there
        are pre-filled values, otherwise new_user.
        """
        if not initial_state:
            return cls(mode="new_user")
        return cls(
            mode="returning_same_page",
            current_page_values=initial_state,
        )
