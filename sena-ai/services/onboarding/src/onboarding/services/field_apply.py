"""field_apply envelope builder — pure module (no IO)."""
from __future__ import annotations

import logging

from onboarding.models.schema_spec import StepSchema
from onboarding.services.coverage import is_eligible

log = logging.getLogger(__name__)


def build_envelope(
    section_id: str,
    field_id: str,
    value: object,
    *,
    row_index: int | None = None,
    confidence: float = 1.0,
    schema: StepSchema,
    enforced: bool = True,
) -> dict | None:
    confidence = max(0.0, min(1.0, float(confidence)))
    if enforced and not is_eligible(section_id, field_id, schema):
        log.debug("field_apply_blocked section=%s field=%s", section_id, field_id)
        return None
    return {
        "type": "field_apply",
        "section_id": section_id,
        "field_id": field_id,
        "row_index": row_index,
        "value": value,
        "source": "voice",
        "confidence": confidence,
    }
