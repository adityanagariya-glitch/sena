"""field_apply envelope builder — pure module (no IO)."""
from __future__ import annotations

from typing import Literal

import structlog

from sena_common.voice.schema_spec import StepSchema
from sena_common.voice.coverage import is_eligible

log = structlog.get_logger(__name__)


def build_envelope(
    section_id: str,
    field_id: str,
    value: object,
    *,
    row_index: int | None = None,
    confidence: float = 1.0,
    schema: StepSchema,
    enforced: bool = True,
    input_method: Literal["typed", "voice"] | None = None,
) -> dict | None:
    """Build a field_apply envelope for emission to the Flutter client.

    ``input_method`` reflects the human-intent channel of the write. When
    None (server-stamped writes, auto-copy mirrors), the key is omitted so
    older clients keep deserialising cleanly. When set, the value is
    surfaced verbatim so the UI can colour/tag the affected field.
    """
    confidence = max(0.0, min(1.0, float(confidence)))
    if enforced and not is_eligible(section_id, field_id, schema):
        log.debug("field_apply_blocked", section=section_id, field=field_id)
        return None
    envelope: dict = {
        "type": "field_apply",
        "section_id": section_id,
        "field_id": field_id,
        "row_index": row_index,
        "value": value,
        "source": "voice",
        "confidence": confidence,
    }
    if input_method is not None:
        envelope["input_method"] = input_method
    return envelope
