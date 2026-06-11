from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class FieldType(str, Enum):
    text = "text"
    textarea = "textarea"
    email = "email"
    phone = "phone"
    date = "date"
    time = "time"
    number = "number"
    currency = "currency"
    boolean = "boolean"
    enum = "enum"
    multi_enum = "multi_enum"


class FieldSpec(BaseModel):
    id: str
    type: FieldType
    label: str | None = None
    required: bool = True
    options: list[str] | None = None
    pattern: str | None = None
    format: str | None = None
    # visible_if: {field_id: expected_value} — skip field if condition not met
    visible_if: dict[str, Any] | None = None
    default: Any | None = None
    # readonly: true → voice agent must NEVER call update_field on this field.
    # Used for identity-bound values (email, externally-managed IDs) that flow
    # from the auth/account system. The dispatcher rejects writes server-side
    # in addition to the prompt's Rule 3 readonly handling.
    readonly: bool = False

    @model_validator(mode="after")
    def options_required_for_enum(self) -> FieldSpec:
        if self.type in (FieldType.enum, FieldType.multi_enum) and not self.options:
            raise ValueError(f"Field '{self.id}' of type '{self.type}' must have options")
        return self


class RepeatableConfig(BaseModel):
    min: int = 0
    max: int = 10


class SectionSpec(BaseModel):
    id: str
    label: str
    # Regular (non-repeatable) section has `fields`
    fields: list[FieldSpec] | None = None
    # Repeatable section has `item_fields` + `repeatable`
    item_fields: list[FieldSpec] | None = None
    repeatable: RepeatableConfig | None = None
    # If set: "Is this the same as <copy_from_if_flagged>?" shortcut
    copy_from_if_flagged: str | None = None
    flag_field: FieldSpec | None = None

    @model_validator(mode="after")
    def validate_section_shape(self) -> SectionSpec:
        if self.repeatable is not None and not self.item_fields:
            raise ValueError(f"Repeatable section '{self.id}' must have item_fields")
        if self.repeatable is None and self.fields is None:
            raise ValueError(f"Section '{self.id}' must have fields or be repeatable with item_fields")
        return self

    @property
    def is_repeatable(self) -> bool:
        return self.repeatable is not None

    def all_fields(self) -> list[FieldSpec]:
        """Return all fields (regular or item_fields for repeatable)."""
        base = list(self.item_fields or []) if self.is_repeatable else list(self.fields or [])
        if self.flag_field:
            base.insert(0, self.flag_field)
        return base


class StepSchema(BaseModel):
    version: str = "v1"
    step_id: str
    step_label: str
    progress_percent: int = Field(ge=0, le=100)
    sections: list[SectionSpec]
    voice_coverage: list[str] = Field(default_factory=list)
    voice_repeatable_sections: list[str] = Field(default_factory=list)

    def required_field_count(self) -> int:
        total = 0
        for section in self.sections:
            for f in section.all_fields():
                if f.required and f.visible_if is None:
                    total += 1
        return total

    def get_section(self, section_id: str) -> SectionSpec | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def get_field_spec(self, section_id: str, field_id: str) -> FieldSpec | None:
        """Look up a FieldSpec by (section_id, field_id).

        Handles both regular sections (fields) and repeatable sections (item_fields).
        Returns None — never raises — for unknown section/field pairs.
        """
        for section in self.sections:
            if section.id != section_id:
                continue
            fields = section.item_fields if section.is_repeatable else (section.fields or [])
            for f in (fields or []):
                if f.id == field_id:
                    return f
            return None  # section found, field not found
        return None  # section not found
