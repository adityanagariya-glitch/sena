from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FieldType = Literal[
    "text", "email", "phone", "date", "enum", "multi_enum",
    "boolean", "number", "textarea", "file", "time", "year", "currency",
    # `use_screen` — the field can ONLY be filled by interacting with the
    # mobile UI (e.g., support_schedule[N].preferred_schedule is a day/time
    # grid). The agent must direct the participant to the screen rather than
    # try to capture by voice. Validators + prompt rules treat as read-only
    # for the voice path.
    "use_screen",
]

BootstrapMode = Literal["new_user", "returning_same_page", "page_handoff"]

NextTargetReason = Literal["next_required", "user_requested", "forced_unlock"]


class Participant(BaseModel):
    model_config = ConfigDict(extra="ignore")
    first_name: str = ""
    display_name: str = ""


class StepInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    label: str
    number: int


class VisibleField(BaseModel):
    # Permissive — Flutter ships UI-rendering metadata on this object that
    # the server doesn't need to interpret (e.g. section labels, row indices,
    # render hints). `extra="ignore"` accepts and drops anything not declared
    # below. The other 5 models in this file stay `extra="forbid"` because
    # they're contract-stable identity/auth objects.
    model_config = ConfigDict(extra="ignore")
    path: str
    label: str
    # `type` is an informational hint passed to the agent — the server never
    # branches on it (writability is driven by `readonly` + the validators).
    # Kept as a plain `str` rather than the FieldType Literal so Flutter can
    # ship any type marker ("int", "year", "use_screen", future additions)
    # without tripping a literal_error. FieldType below documents the known
    # canonical set but is no longer enforced here.
    type: str
    required: bool
    readonly: bool
    value: object | None = None
    enum_values: list[str] | None = None
    validations_hint: str | None = None
    # Repeatable-section row index. Already encoded in `path` (e.g.
    # "ndis_goals[0].title") but Flutter sends it parallel for convenience.
    repeatable_index: int | None = None
    # Section id for fields belonging to a repeatable section ("ndis_goals",
    # "support_schedule", "emergency_contacts"). Redundant with the path
    # prefix but useful for grouped UI rendering.
    section: str | None = None


class NextTarget(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    label: str
    # `reason` is an informational hint for the agent (WHY this is next) — the
    # server never branches on the exact value. Kept as a plain `str` rather
    # than the NextTargetReason Literal so Flutter can ship any UI-driven marker
    # ("pending_uploads", "pending_expiry_after_upload", future additions)
    # without tripping a literal_error that invalidates the whole TurnPayload
    # and kills the session. NextTargetReason documents the canonical set.
    reason: str


class LastRejection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    reason: str
    code: str | None = None


class PendingConfirmation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    heard_value: str


class TurnPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    participant: Participant
    step: StepInfo
    bootstrap_mode: BootstrapMode
    # Cross-screen bucket carries step summaries as nested dicts
    # ({name, dob, _step_label, ...}), not flat strings.
    prior_steps: dict[str, Any] = Field(default_factory=dict)
    visible_fields: list[VisibleField]
    next_target: NextTarget | None = None
    last_rejection: LastRejection | None = None
    pending_confirmation: PendingConfirmation | None = None
