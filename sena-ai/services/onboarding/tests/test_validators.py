"""Tests for the onboarding validators package.

All tests are pure — no Redis, no Gemini, no async.
Each validator function is a pure function; tests call it directly with
known-good and known-bad values and assert the exact code / None.

Adding a new validator = one row in the parametrize table, not a new test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import StepSchema
from onboarding.services.validators import (
    ValidationRejection,
    next_required_field,
    validate_cross_fields,
    validate_field,
    validate_step_complete,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(**kwargs) -> FormState:
    defaults: dict = dict(session_id="s-test", step_id="step1", participant_id="p-test")
    defaults.update(kwargs)
    return FormState(**defaults)


def _fv(value):
    """Minimal FieldValue-shaped dict for state fixtures."""
    return {"value": value, "source": "voice", "confidence": 1.0}


def _load_schema(name: str) -> StepSchema:
    return StepSchema.model_validate(json.loads((FIXTURES / name).read_text()))


# ── validate_field — parametrized table ──────────────────────────────────────
#
# Each row: (value, section_id, field_id, expected_code)
#   expected_code=None  → validator must return None (pass)
#   expected_code=str   → validator must return a ValidationRejection with that code

@pytest.mark.parametrize("value,section,field,expected_code", [
    # ── AU phone ──────────────────────────────────────────────────────────────
    ("0412345678",    "basics", "phone", None),
    ("0212345678",    "basics", "phone", None),
    ("0312345678",    "basics", "phone", None),
    ("0712345678",    "basics", "phone", None),
    ("0812345678",    "basics", "phone", None),
    ("+61412345678",  "basics", "phone", None),
    ("1300123456",    "basics", "phone", None),
    ("1800123456",    "basics", "phone", None),
    ("131234",        "basics", "phone", None),        # 13-prefix (6 digits)
    ("12",            "basics", "phone", "phone_invalid_format"),
    ("04123",         "basics", "phone", "phone_invalid_format"),
    ("0512345678",    "basics", "phone", "phone_invalid_format"),  # 05xx invalid prefix
    ("0912345678",    "basics", "phone", "phone_invalid_format"),  # 09xx invalid prefix
    ("1234567890",    "basics", "phone", "phone_invalid_format"),
    ("",              "basics", "phone", "required"),

    # ── Full name ─────────────────────────────────────────────────────────────
    ("Jane Doe",           "basics", "full_name", None),
    ("Mary Jane Watson",   "basics", "full_name", None),
    ("Jane",               "basics", "full_name", "full_name_requires_first_last"),
    ("",                   "basics", "full_name", "required"),
    ("A" * 26 + " Doe",   "basics", "full_name", "full_name_first_too_long"),
    ("Jane " + "B" * 26,  "basics", "full_name", "full_name_last_too_long"),

    # ── Date of birth ─────────────────────────────────────────────────────────
    ("1985-01-01", "basics", "date_of_birth", None),        # clearly over 18
    ("1970-06-15", "basics", "date_of_birth", None),        # over 18
    ("2012-01-01", "basics", "date_of_birth", "dob_under_18"),   # clearly under 18 (14 in 2026)
    ("2030-01-01", "basics", "date_of_birth", "dob_in_future"),
    ("",           "basics", "date_of_birth", "required"),

    # ── NDIS number ───────────────────────────────────────────────────────────
    ("123456789",   "plan_info", "ndis_number", None),       # exactly 9 digits
    ("43 567 8910", "plan_info", "ndis_number", None),       # spaces stripped → 9 digits
    ("12345678",    "plan_info", "ndis_number", "ndis_wrong_length"),   # 8 digits
    ("1234567890",  "plan_info", "ndis_number", "ndis_wrong_length"),   # 10 digits
    ("ABC123456",   "plan_info", "ndis_number", "ndis_wrong_length"),   # letters stripped → 6 digits
    ("",            "plan_info", "ndis_number", "required"),

    # ── Postcode ──────────────────────────────────────────────────────────────
    ("2000", "home_address", "zip_code", None),
    ("0200", "home_address", "zip_code", None),
    ("9999", "home_address", "zip_code", None),
    ("123",  "home_address", "zip_code", "postcode_invalid"),
    ("12345","home_address", "zip_code", "postcode_invalid"),
    ("ABCD", "home_address", "zip_code", "postcode_invalid"),
    ("",     "home_address", "zip_code", "required"),

    # ── Duration (schedule of supports) ──────────────────────────────────────
    ("1",    "schedule_of_supports", "duration_hours", None),
    ("12",   "schedule_of_supports", "duration_hours", None),
    ("24",   "schedule_of_supports", "duration_hours", None),
    ("24.0", "schedule_of_supports", "duration_hours", None),   # whole number as float string
    ("0",    "schedule_of_supports", "duration_hours", "duration_too_short"),
    ("25",   "schedule_of_supports", "duration_hours", "duration_too_long"),
    ("1.5",  "schedule_of_supports", "duration_hours", "duration_not_a_number"),  # fails regex before float check
    ("abc",  "schedule_of_supports", "duration_hours", "duration_not_a_number"),
    # Schema marks duration_hours as required: false — empty must PASS.
    ("",     "schedule_of_supports", "duration_hours", None),

    # ── Email ─────────────────────────────────────────────────────────────────
    ("user@example.com",   "basics", "email", None),
    ("u@sub.domain.com.au","basics", "email", None),
    ("notanemail",         "basics", "email", "email_invalid"),
    ("missing@",           "basics", "email", "email_invalid"),
    ("",                   "basics", "email", "required"),
    # RFC 5321 length guards (V2 fix — long-domain transcription artefacts)
    ("u@" + "a" * 64 + ".com",                                              "basics", "email", "email_invalid"),  # label > 63
    ("u@" + "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 63, "basics", "email", "email_invalid"),  # domain > 253

    # ── Allergy description (min 5, max 250) ──────────────────────────────────
    ("Causes severe rash after contact",  "allergies", "description", None),
    ("abc",                               "allergies", "description", "description_too_short"),
    ("",                                  "allergies", "description", "required"),

    # ── Emergency contact name (max 25) ───────────────────────────────────────
    ("Alice Smith",      "emergency_contacts", "name", None),
    ("A" * 25,           "emergency_contacts", "name", None),    # exactly 25 → pass
    ("A" * 26,           "emergency_contacts", "name", "text_too_long"),
    ("",                 "emergency_contacts", "name", "required"),

    # ── NDIS goal ─────────────────────────────────────────────────────────────
    ("Improve independence in daily living", "ndis_goals", "goal", None),
    ("",                                     "ndis_goals", "goal", "required"),
])
def test_validate_field(value, section, field, expected_code):
    result = validate_field(section, field, value)
    if expected_code is None:
        assert result is None, (
            f"Expected PASS for {section}.{field}={value!r} "
            f"but got rejection: code={getattr(result, 'code', None)!r} "
            f"reason={getattr(result, 'reason_human', None)!r}"
        )
    else:
        assert result is not None, (
            f"Expected rejection '{expected_code}' for {section}.{field}={value!r} "
            f"but validator passed (returned None)"
        )
        assert result.code == expected_code, (
            f"Wrong code for {section}.{field}={value!r}: "
            f"expected '{expected_code}' got '{result.code}' "
            f"(reason: {result.reason_human!r})"
        )
        # Every rejection the model reads aloud must have non-empty human text
        assert result.reason_human, (
            f"Rejection {result.code} for {section}.{field} has empty reason_human — "
            f"model will say nothing useful to the participant"
        )


def test_validate_field_unknown_pair_returns_none():
    """Unknown (section, field) pairs must pass — drift detection is tools.py's job."""
    assert validate_field("nonexistent_section", "nonexistent_field", "any value") is None


def test_validate_field_plan_end_cross_field_fail():
    """plan_end validator cross-references plan_start from FormState."""
    state = _state(values={"plan_info": {"plan_start": _fv("2025-06-01")}})
    result = validate_field("plan_info", "plan_end", "2025-01-01", state=state)
    assert result is not None
    assert result.code == "plan_end_not_after_start"


def test_validate_field_plan_end_cross_field_pass():
    state = _state(values={"plan_info": {"plan_start": _fv("2025-01-01")}})
    result = validate_field("plan_info", "plan_end", "2026-12-31", state=state)
    assert result is None


def test_validate_field_plan_manager_not_required_when_self_managed():
    """plan_manager is required only when plan_management = 'Plan Managed'."""
    state = _state(values={"plan_info": {"plan_management": _fv("Self Managed")}})
    result = validate_field("plan_info", "plan_manager", "", state=state)
    assert result is None  # not required for self-managed


def test_validate_field_plan_manager_required_when_plan_managed():
    state = _state(values={"plan_info": {"plan_management": _fv("Plan Managed")}})
    result = validate_field("plan_info", "plan_manager", "", state=state)
    assert result is not None
    assert result.code == "required"


def test_validation_rejection_model_dump_shape():
    """ValidationRejection serialises correctly for the FunctionResponse payload."""
    rej = ValidationRejection(code="phone_invalid_format", reason_human="Enter a valid number")
    dumped = rej.model_dump()
    assert dumped["code"] == "phone_invalid_format"
    assert dumped["reason_human"] == "Enter a valid number"
    assert "suggested_fix" in dumped  # field exists even when None


# ── Cross-field invariants ────────────────────────────────────────────────────

class TestCrossFields:
    def test_empty_values_no_rejections(self):
        assert validate_cross_fields({}) == []

    def test_plan_end_after_start_passes(self):
        values = {
            "plan_info": {
                "plan_start": _fv("2025-01-01"),
                "plan_end": _fv("2026-12-31"),
            }
        }
        codes = [r.code for r in validate_cross_fields(values)]
        assert "plan_end_not_after_start" not in codes

    def test_plan_end_before_start_fails(self):
        values = {
            "plan_info": {
                "plan_start": _fv("2026-06-01"),
                "plan_end": _fv("2025-01-01"),
            }
        }
        codes = [r.code for r in validate_cross_fields(values)]
        assert "plan_end_not_after_start" in codes

    def test_plan_end_same_as_start_fails(self):
        values = {
            "plan_info": {
                "plan_start": _fv("2025-07-01"),
                "plan_end": _fv("2025-07-01"),
            }
        }
        codes = [r.code for r in validate_cross_fields(values)]
        assert "plan_end_not_after_start" in codes

    def test_emergency_email_matches_client_fails(self):
        values = {
            "basics": {"email": _fv("shared@example.com")},
            "emergency_contacts": [{"email": _fv("shared@example.com")}],
        }
        codes = [r.code for r in validate_cross_fields(values)]
        assert "emergency_email_matches_client" in codes

    def test_emergency_email_different_from_client_passes(self):
        values = {
            "basics": {"email": _fv("client@example.com")},
            "emergency_contacts": [{"email": _fv("contact@example.com")}],
        }
        codes = [r.code for r in validate_cross_fields(values)]
        assert "emergency_email_matches_client" not in codes

    def test_emergency_email_duplicate_across_rows_fails(self):
        values = {
            "emergency_contacts": [
                {"email": _fv("same@example.com")},
                {"email": _fv("same@example.com")},
            ],
        }
        codes = [r.code for r in validate_cross_fields(values)]
        assert "emergency_email_duplicate" in codes

    def test_emergency_email_unique_across_rows_passes(self):
        values = {
            "emergency_contacts": [
                {"email": _fv("alice@example.com")},
                {"email": _fv("bob@example.com")},
            ],
        }
        codes = [r.code for r in validate_cross_fields(values)]
        assert "emergency_email_duplicate" not in codes

    def test_cross_field_rejections_have_human_reason(self):
        values = {
            "plan_info": {
                "plan_start": _fv("2026-01-01"),
                "plan_end": _fv("2025-01-01"),
            }
        }
        for rej in validate_cross_fields(values):
            assert rej.reason_human, f"Cross-field rejection {rej.code} missing reason_human"


# ── next_required_field ───────────────────────────────────────────────────────

class TestNextRequiredField:
    def test_empty_state_returns_dict(self):
        schema = _load_schema("schema_personal_information.json")
        state = _state(step_id="step1")
        nrf = next_required_field(schema, state)
        assert nrf is not None
        assert set(nrf.keys()) >= {"section_id", "field_id", "label"}

    def test_empty_state_first_section_is_basics(self):
        schema = _load_schema("schema_personal_information.json")
        state = _state(step_id="step1")
        nrf = next_required_field(schema, state)
        assert nrf is not None
        assert nrf["section_id"] == "basics"

    def test_filling_basics_moves_past_basics(self):
        schema = _load_schema("schema_personal_information.json")
        state = _state(step_id="step1", values={
            "basics": {
                "full_name":           _fv("Jane Doe"),
                "email":               _fv("jane@example.com"),
                "phone":               _fv("0412345678"),
                "date_of_birth":       _fv("1985-06-15"),
                "gender":              _fv("Female"),
                "preferred_language":  _fv("English"),
                "interpreter_required": _fv("No"),
                "about_me":            _fv("Short bio here."),
            }
        })
        nrf = next_required_field(schema, state)
        # Should move past basics — either None (if basics was the only section
        # with required fields) or a field in a later section
        if nrf is not None:
            assert nrf["section_id"] != "basics", (
                f"Expected next field AFTER basics but got {nrf}"
            )

    def test_ndis_schema_empty_returns_plan_info_field(self):
        schema = _load_schema("schema_ndis_plan_details.json")
        state = _state(step_id="step3")
        nrf = next_required_field(schema, state)
        assert nrf is not None
        assert nrf["section_id"] == "plan_info"

    def test_result_is_none_or_dict(self):
        """Smoke test: never raises, always returns None or valid dict."""
        schema = _load_schema("schema_medical_information.json")
        state = _state(step_id="step5")
        nrf = next_required_field(schema, state)
        assert nrf is None or (isinstance(nrf, dict) and "section_id" in nrf)


# ── validate_step_complete ────────────────────────────────────────────────────

class TestValidateStepComplete:
    def test_empty_state_has_rejections(self):
        schema = _load_schema("schema_personal_information.json")
        state = _state(step_id="step1")
        rejections = validate_step_complete(schema, state)
        assert len(rejections) > 0

    def test_empty_state_contains_required_field_missing(self):
        schema = _load_schema("schema_personal_information.json")
        state = _state(step_id="step1")
        codes = [r.code for r in validate_step_complete(schema, state)]
        assert "required_field_missing" in codes

    def test_invalid_phone_produces_field_rejection(self):
        schema = _load_schema("schema_personal_information.json")
        state = _state(step_id="step1", values={
            "basics": {
                "full_name":           _fv("Jane Doe"),
                "email":               _fv("jane@example.com"),
                "phone":               _fv("not-a-phone"),
                "date_of_birth":       _fv("1985-01-01"),
                "gender":              _fv("Female"),
                "preferred_language":  _fv("English"),
                "interpreter_required": _fv("No"),
            },
        })
        codes = [r.code for r in validate_step_complete(schema, state)]
        assert "phone_invalid_format" in codes

    def test_all_rejections_have_human_reason(self):
        schema = _load_schema("schema_personal_information.json")
        state = _state(step_id="step1")
        for rej in validate_step_complete(schema, state):
            assert rej.reason_human, (
                f"Rejection {rej.code} in validate_step_complete has empty reason_human"
            )

    def test_ndis_empty_state_produces_rejections(self):
        schema = _load_schema("schema_ndis_plan_details.json")
        state = _state(step_id="step3")
        rejections = validate_step_complete(schema, state)
        assert len(rejections) > 0

    def test_medical_empty_state_produces_rejections(self):
        schema = _load_schema("schema_medical_information.json")
        state = _state(step_id="step5")
        rejections = validate_step_complete(schema, state)
        assert len(rejections) > 0


# ── validate_field — field_spec options enforcement (V3/S5) ──────────────────


class _FakeFieldSpec:
    """Minimal FieldSpec stand-in for testing the options-check path."""

    def __init__(self, field_type: str, options: list[str]) -> None:
        self.type = field_type  # attribute MUST be `type` to match FieldSpec
        self.options = options


_COMM_OPTIONS = [
    "AAC Device",
    "Verbal (spoken)",
    "Written (text/email)",
    "Auslan or sign-supported English",
    "Communication board or book",
    "Through a support person or family member",
    "Visual supports (images, diagrams)",
]

_COMM_SPEC = _FakeFieldSpec("multi_enum", _COMM_OPTIONS)


class TestValidateFieldEnumOptions:
    def test_valid_option_passes(self) -> None:
        result = validate_field(
            "requirements", "mode_of_communication", ["Verbal (spoken)"], field_spec=_COMM_SPEC
        )
        assert result is None

    def test_invalid_option_rejected(self) -> None:
        result = validate_field(
            "requirements", "mode_of_communication", ["Walkie Talkies"], field_spec=_COMM_SPEC
        )
        assert result is not None
        assert result.code == "enum_invalid"
        assert result.allowed_values == _COMM_OPTIONS

    def test_case_insensitive_pass(self) -> None:
        result = validate_field(
            "requirements", "mode_of_communication", ["verbal (spoken)"], field_spec=_COMM_SPEC
        )
        assert result is None

    def test_no_field_spec_skips_options_check(self) -> None:
        # Without field_spec, any non-empty list passes (backward compatibility)
        result = validate_field(
            "requirements", "mode_of_communication", ["Walkie Talkies"]
        )
        assert result is None  # no field_spec → only required check runs

    def test_empty_list_still_triggers_required(self) -> None:
        result = validate_field(
            "requirements", "mode_of_communication", [], field_spec=_COMM_SPEC
        )
        assert result is not None
        assert result.code == "required"
