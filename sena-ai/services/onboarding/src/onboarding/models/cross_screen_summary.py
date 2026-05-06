"""
Cross-screen shared-context models.

When a participant finishes one onboarding step, a `StepSummary` is written to
their per-(tenant_id, participant_id) bucket. When the next step's voice
session starts, the bucket (a `CrossScreenContext`) is read and rendered into
the system prompt so the assistant can reference earlier disclosures naturally.

The split between `verbatim` (high-signal warmth fields preserved exactly) and
`compressed` (everything else, losslessly key-shortened) is documented in the
PRD at .planning/PRD-cross-screen-context.md and the implementation plan at
.claude/plans/no-graceful-muffin.md. Schema is versioned via `schema_version`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StepSummary(BaseModel):
    """One completed onboarding step's distilled record.

    `verbatim` holds the six high-signal fields (`name, dob, gender, goals,
    hobbies, interests`) preserved exactly when present in the source FormState.
    `compressed` is a deterministic, lossless JSON string of the residual
    populated fields encoded via the `KEY_ALIASES` table in
    `services/cross_screen_context.py`. Round-trip with `decompress(s)` is
    asserted by the property test in `tests/test_cross_screen_context.py`.
    """

    model_config = {"extra": "ignore"}

    step_number: int
    step_label: str
    completed_at: datetime = Field(default_factory=_utcnow)
    session_id: str
    verbatim: dict[str, Any] = Field(default_factory=dict)
    compressed: str = ""
    completion_pct: float = 0.0
    schema_version: int = 1


class CrossScreenContext(BaseModel):
    """Aggregate bucket of per-step summaries for one participant.

    Order is by `step_number` ascending. Renderer caps verbatim inlining to the
    last 5 steps (older ones collapse to compressed-only) so the prompt cannot
    grow unboundedly when a participant has many completed steps.
    """

    model_config = {"extra": "ignore"}

    summaries: list[StepSummary] = Field(default_factory=list)
    schema_version: int = 1

    def is_empty(self) -> bool:
        return not self.summaries
