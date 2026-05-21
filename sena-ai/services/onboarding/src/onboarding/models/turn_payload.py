from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FieldType = Literal[
    "text", "email", "phone", "date", "enum", "multi_enum",
    "boolean", "number", "textarea", "file", "time", "year", "currency",
]

BootstrapMode = Literal["new_user", "returning_same_page", "page_handoff"]

NextTargetReason = Literal["next_required", "user_requested", "forced_unlock"]


class Participant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_name: str = ""
    display_name: str = ""


class StepInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    number: int


class VisibleField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    label: str
    type: FieldType
    required: bool
    readonly: bool
    value: object | None = None
    enum_values: list[str] | None = None
    validations_hint: str | None = None


class NextTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    label: str
    reason: NextTargetReason


class LastRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    reason: str
    code: str | None = None


class PendingConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    heard_value: str


class TurnPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participant: Participant
    step: StepInfo
    bootstrap_mode: BootstrapMode
    prior_steps: dict[str, str] = Field(default_factory=dict)
    visible_fields: list[VisibleField]
    next_target: NextTarget | None = None
    last_rejection: LastRejection | None = None
    pending_confirmation: PendingConfirmation | None = None
