from __future__ import annotations

import pytest
from pydantic import ValidationError

from voice.turn_payload import TurnPayload


def _valid_turn() -> dict:
    return {
        "participant": {"first_name": "Jane", "display_name": "Jane Doe"},
        "step": {"id": "personal_information", "label": "Personal Details", "number": 1},
        "bootstrap_mode": "new_user",
        "prior_steps": {},
        "visible_fields": [
            {
                "path": "basics.full_name",
                "label": "Full Name",
                "type": "text",
                "required": True,
                "readonly": False,
                "value": None,
                "enum_values": None,
                "validations_hint": None,
            }
        ],
        "next_target": {
            "path": "basics.full_name",
            "label": "Full Name",
            "reason": "next_required",
        },
        "last_rejection": None,
        "pending_confirmation": None,
    }


def test_turn_payload_parses_minimal_valid_payload() -> None:
    tp = TurnPayload.model_validate(_valid_turn())
    assert tp.participant.first_name == "Jane"
    assert tp.visible_fields[0].path == "basics.full_name"


def test_turn_payload_rejects_unknown_field_type() -> None:
    bad = _valid_turn()
    bad["visible_fields"][0]["type"] = "magic"
    with pytest.raises(ValidationError):
        TurnPayload.model_validate(bad)


def test_turn_payload_rejects_unknown_bootstrap_mode() -> None:
    bad = _valid_turn()
    bad["bootstrap_mode"] = "weird"
    with pytest.raises(ValidationError):
        TurnPayload.model_validate(bad)


def test_turn_payload_serialises_to_compact_json() -> None:
    tp = TurnPayload.model_validate(_valid_turn())
    out = tp.model_dump_json()
    assert '"first_name":"Jane"' in out
    assert " " not in out.split('"participant"')[0]  # no whitespace before first key


def test_visible_field_enum_values_optional_for_text() -> None:
    payload = _valid_turn()
    payload["visible_fields"][0]["enum_values"] = None
    tp = TurnPayload.model_validate(payload)
    assert tp.visible_fields[0].enum_values is None


def test_visible_field_enum_values_list_of_strings_for_enum() -> None:
    payload = _valid_turn()
    enum_options = ["Male", "Female", "Non-binary", "Prefer not to say", "Other"]
    payload["visible_fields"].append({
        "path": "basics.gender",
        "label": "Gender",
        "type": "enum",
        "required": True,
        "readonly": False,
        "value": None,
        "enum_values": enum_options,
        "validations_hint": None,
    })
    tp = TurnPayload.model_validate(payload)
    assert tp.visible_fields[1].enum_values == enum_options
