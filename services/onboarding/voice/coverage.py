"""Voice coverage check — pure module (no IO)."""
from __future__ import annotations

from schema_spec import StepSchema


def is_eligible(section_id: str, field_id: str, schema: StepSchema) -> bool:
    if not schema.voice_coverage:
        return False
    return f"{section_id}.{field_id}" in schema.voice_coverage


def is_repeatable_eligible(section_id: str, schema: StepSchema) -> bool:
    return section_id in schema.voice_repeatable_sections


def coverage_paths(schema: StepSchema) -> list[str]:
    return list(schema.voice_coverage)
