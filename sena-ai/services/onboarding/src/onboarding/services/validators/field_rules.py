"""Per-field validators mirroring Flutter lib/core/utils/validators.dart.

Error strings are byte-for-byte copies of AppStrings constants so the
assistant's voice matches what the participant reads on screen.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from .base import ValidationRejection

# ── AppStrings constants (byte-for-byte) ────────────────────────────────────
_FIELD_REQUIRED = "This field is required."
_EMAIL_INVALID = "Enter a valid email"
_AU_MOBILE_INVALID = "Enter a valid Australian phone number (+61 followed by 9 digits starting with 2, 3, 4, 7 or 8)"
_POSTCODE_INVALID = "Postcode must be exactly 4 digits (0000–9999)"
_FULL_NAME_REQUIRES_FIRST_LAST = "Enter full name (e.g. Jane Doe)"
_NDIS_WRONG_LENGTH = "NDIS number must be exactly 9 digits"
_DATE_NOT_FUTURE = "Date must not be in the future"
_DATE_AFTER_START = "Date must be after start date"
_DATE_MIN_18 = "You must be at least 18 years old"
_AMOUNT_POSITIVE = "Amount must be greater than zero"
_DURATION_MIN_1 = "Duration must be at least 1 hour when provided"
_DURATION_NUMBERS_ONLY = "Duration must contain numbers only"
_DURATION_MAX_24 = "Duration must be less than or equal to 24 hours"
_TIME_SLOTS_OVERLAP = "Time slots must not overlap"
_TIME_INVALID_RANGE = "Start time must be before end time"
_TIME_HM_INVALID = "Use 24-hour time as HH:mm (e.g. 09:30)."
_BSB_INVALID = "BSB must be exactly 6 digits (e.g. 062000)"
_ABN_INVALID = "Super fund ABN must be exactly 11 digits (e.g. 65714394898)"
_EXPIRY_NOT_FUTURE = "Expiry date must be a future date"
_AU_STATE_INVALID = "Please provide an Australian state (NSW, VIC, QLD, SA, WA, TAS, ACT, or NT)"


def _at_most(n: int) -> str:
    return f"Must be at most {n} characters"


def _at_least(n: int) -> str:
    return f"Must be at least {n} characters"


# ── Regex ────────────────────────────────────────────────────────────────────
_AU_PHONE = re.compile(r"^(?:\+61[2-478]\d{8}|0[2-478]\d{8}|1300\d{6}|1800\d{6}|13\d{4})$")
# Standard email — matches Flutter client spec `client_onboarding_validations.md`:
# unbounded label count, no disposable-domain check. Used for `basics.email`
# (pre-filled from auth, not user-typed) and `plan_info.contact_email` /
# `plan_info.billing_email` (≤50 chars enforced separately).
_EMAIL_RE_STANDARD = re.compile(
    r"^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)+$",
    re.IGNORECASE,
)
# Strict email — used ONLY for `emergency_contacts.email` per spec line 47.
# 3-label cap + disposable-domain blocklist + RFC 5321 length limits.
_EMAIL_RE = re.compile(
    r"^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+){1,3}$",
    re.IGNORECASE,
)
_DISPOSABLE_EMAIL_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com",
    "tempmail.com", "throwaway.email", "yopmail.com", "fakeinbox.com",
    "trashmail.com", "sharklasers.com", "getairmail.com", "dispostable.com",
})
_POSTCODE = re.compile(r"^\d{4}$")
_HM24 = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_BSB_RE = re.compile(r"^\d{6}$")
_ABN_RE = re.compile(r"^\d{11}$")


# ── Helper extractors ────────────────────────────────────────────────────────
def _fv(raw: Any) -> Any:
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _str(v: Any) -> str:
    x = _fv(v)
    return (x or "").strip() if isinstance(x, str) else (str(x) if x is not None else "")


def _list(v: Any) -> list:
    x = _fv(v)
    return x if isinstance(x, list) else []


# ── Primitive validators ─────────────────────────────────────────────────────
def _required(v: str) -> ValidationRejection | None:
    return None if v else ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)


def _max_len(v: str, n: int, code: str) -> ValidationRejection | None:
    return None if len(v) <= n else ValidationRejection(code=code, reason_human=_at_most(n))


def _min_len(v: str, n: int, code: str) -> ValidationRejection | None:
    return None if len(v) >= n else ValidationRejection(code=code, reason_human=_at_least(n))


def _au_phone(v: str, *, required: bool = True) -> ValidationRejection | None:
    stripped = re.sub(r"\s+", "", v)
    if not stripped:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED) if required else None
    if not _AU_PHONE.match(stripped):
        return ValidationRejection(code="phone_invalid_format", reason_human=_AU_MOBILE_INVALID,
                                   suggested_fix="Australian numbers: 04XX XXX XXX, 02/03/07/08 XXXX XXXX, or +61...")
    return None


def _email(
    v: str,
    *,
    required: bool = True,
    strict: bool = True,
    max_len: int | None = None,
) -> ValidationRejection | None:
    """Email validator. Three modes, matching `client_onboarding_validations.md`:

    - `strict=True` (default, emergency_contacts.email): 3-label-cap regex,
      RFC 5321 length checks, disposable-domain blocklist.
    - `strict=False` (basics.email, plan_info emails): unbounded-label standard
      regex, NO disposable check, NO length cap unless `max_len` is set.
    - `max_len`: extra length cap (spec sets 50 for plan_info contact/billing).
    """
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED) if required else None
    if max_len is not None and len(v) > max_len:
        return ValidationRejection(code="email_invalid", reason_human=_EMAIL_INVALID)
    pattern = _EMAIL_RE if strict else _EMAIL_RE_STANDARD
    if not pattern.match(v):
        return ValidationRejection(code="email_invalid", reason_human=_EMAIL_INVALID)
    if not strict:
        return None
    # Strict-only: RFC 5321 length checks + disposable-domain blocklist.
    domain = v.lower().rsplit("@", 1)[-1]
    if len(domain) > 253 or any(len(lbl) > 63 for lbl in domain.split(".")):
        return ValidationRejection(code="email_invalid", reason_human=_EMAIL_INVALID)
    if domain in _DISPOSABLE_EMAIL_DOMAINS:
        return ValidationRejection(
            code="email_disposable",
            reason_human="Please use a non-disposable email address.",
            suggested_fix=(
                "Disposable-inbox domains (mailinator, guerrillamail, etc.) are "
                "not accepted — please provide a permanent email."
            ),
        )
    return None


# ── Field-level validators ───────────────────────────────────────────────────

def _v_full_name(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    s = re.sub(r"\s+", " ", v.strip())
    parts = s.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        return ValidationRejection(code="full_name_requires_first_last",
                                   reason_human=_FULL_NAME_REQUIRES_FIRST_LAST,
                                   suggested_fix="Provide both first and last name separated by a space.")
    first, last = parts[0], parts[1].strip()
    if len(first) > 25:
        return ValidationRejection(code="full_name_first_too_long", reason_human=_at_most(25))
    if len(last) > 25:
        return ValidationRejection(code="full_name_last_too_long", reason_human=_at_most(25))
    return None


def _v_email_required(raw: Any, _state: Any) -> ValidationRejection | None:
    """STRICT email — used ONLY by `emergency_contacts.email` per spec line 47.
    Applies 3-label cap + RFC 5321 length + disposable-domain blocklist."""
    return _email(_str(raw), required=True, strict=True)


def _v_email_standard_required(raw: Any, _state: Any) -> ValidationRejection | None:
    """STANDARD email — used by `basics.email` per spec line 15. No disposable
    check (auth-prefilled, not user-typed). Standard regex only."""
    return _email(_str(raw), required=True, strict=False)


def _v_phone_au_required(raw: Any, _state: Any) -> ValidationRejection | None:
    return _au_phone(_str(raw), required=True)


def _v_phone_au_optional(raw: Any, _state: Any) -> ValidationRejection | None:
    return _au_phone(_str(raw), required=False)


def _v_dob(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    try:
        dob = date.fromisoformat(v)
    except ValueError:
        return ValidationRejection(code="dob_invalid_format", reason_human=_DATE_NOT_FUTURE,
                                   suggested_fix="Use YYYY-MM-DD format.")
    today = date.today()
    if dob > today:
        return ValidationRejection(code="dob_in_future", reason_human=_DATE_NOT_FUTURE)
    age = today.year - dob.year
    had_birthday = (today.month, today.day) >= (dob.month, dob.day)
    if not had_birthday:
        age -= 1
    if age < 18:
        return ValidationRejection(code="dob_under_18", reason_human=_DATE_MIN_18,
                                   suggested_fix="Participant must be at least 18 years old.")
    return None


def _v_gender_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    return None if v else ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)


def _v_about_me(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return None  # optional
    return _max_len(v, 250, "about_me_too_long")


def _v_preferred_language(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    # Can also be a list of strings (multi-select)
    if not v:
        lst = _list(raw)
        if not lst:
            return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    return None


def _v_postcode(raw: Any, _state: Any) -> ValidationRejection | None:
    v = re.sub(r"\s+", "", _str(raw))
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    if not _POSTCODE.match(v):
        return ValidationRejection(code="postcode_invalid", reason_human=_POSTCODE_INVALID,
                                   suggested_fix="Australian postcodes are exactly 4 digits, e.g. 2000.")
    return None


_AU_STATE_ABBREVS = frozenset({"NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT"})

# Full-name → abbreviation map for voice transcriptions
_AU_STATE_ALIASES: dict[str, str] = {
    "new south wales": "NSW",
    "victoria": "VIC",
    "queensland": "QLD",
    "south australia": "SA",
    "western australia": "WA",
    "tasmania": "TAS",
    "australian capital territory": "ACT",
    "canberra": "ACT",
    "northern territory": "NT",
    "darwin": "NT",
}


def _v_au_state(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw).strip()
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    normalised = _AU_STATE_ALIASES.get(v.lower(), v.upper())
    if normalised not in _AU_STATE_ABBREVS:
        return ValidationRejection(
            code="au_state_invalid",
            reason_human=_AU_STATE_INVALID,
            suggested_fix=(
                "Australian states: NSW, VIC, QLD, SA, WA, TAS, ACT, NT. "
                f"'{v}' is not a recognised Australian state."
            ),
        )
    return None


def _v_text_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    return None if v else ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)


def _v_ndis_number(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    digits = re.sub(r"\D", "", v)
    if not digits:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    if len(digits) != 9:
        return ValidationRejection(code="ndis_wrong_length", reason_human=_NDIS_WRONG_LENGTH,
                                   suggested_fix="NDIS number is exactly 9 digits, e.g. 123456789.")
    return None


def _v_plan_end(raw: Any, state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    # Cross-field check against plan_start
    if state is not None:
        start_raw = ((state.values.get("plan_info") or {}).get("plan_start") or {})
        start_str = start_raw.get("value") if isinstance(start_raw, dict) else start_raw
        if start_str:
            try:
                if date.fromisoformat(v) <= date.fromisoformat(str(start_str)):
                    return ValidationRejection(code="plan_end_not_after_start",
                                               reason_human=_DATE_AFTER_START,
                                               suggested_fix="Plan end date must be after the plan start date.")
            except ValueError:
                pass
    return None


def _v_plan_management(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    return None if v else ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)


def _v_plan_manager_conditional(raw: Any, state: Any) -> ValidationRejection | None:
    """Required only when plan_management = 'Plan Managed'."""
    if state is not None:
        mgmt_raw = ((state.values.get("plan_info") or {}).get("plan_management") or {})
        mgmt = mgmt_raw.get("value") if isinstance(mgmt_raw, dict) else mgmt_raw
        if mgmt != "Plan Managed":
            return None
    v = _str(raw)
    return None if v else ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)


def _v_email_conditional(raw: Any, state: Any) -> ValidationRejection | None:
    """Required email only when plan_management = 'Plan Managed'. Standard
    regex + ≤50 chars per spec line 94-95 (no disposable check)."""
    if state is not None:
        mgmt_raw = ((state.values.get("plan_info") or {}).get("plan_management") or {})
        mgmt = mgmt_raw.get("value") if isinstance(mgmt_raw, dict) else mgmt_raw
        if mgmt != "Plan Managed":
            return _email(_str(raw), required=False, strict=False, max_len=50)
    return _email(_str(raw), required=True, strict=False, max_len=50)


def _v_amount_optional(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return None
    try:
        n = float(v.replace(",", ""))
        if n <= 0:
            return ValidationRejection(code="amount_not_positive", reason_human=_AMOUNT_POSITIVE)
    except ValueError:
        return ValidationRejection(code="amount_invalid", reason_human=_AMOUNT_POSITIVE)
    return None


def _v_duration_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    if not re.match(r"^\d+(?:\.0+)?$", v):
        return ValidationRejection(code="duration_not_a_number", reason_human=_DURATION_NUMBERS_ONLY)
    n = float(v)
    if n % 1 != 0:
        return ValidationRejection(code="duration_not_whole", reason_human=_DURATION_NUMBERS_ONLY)
    i = int(n)
    if i < 1:
        return ValidationRejection(code="duration_too_short", reason_human=_DURATION_MIN_1)
    if i > 24:
        return ValidationRejection(code="duration_too_long", reason_human=_DURATION_MAX_24)
    return None


def _v_duration_optional(raw: Any, _state: Any) -> ValidationRejection | None:
    """Same range rules as `_v_duration_required` but empty is allowed.

    Schema fixtures mark `schedule_of_supports.duration_hours` as
    `required: false`, so we must not reject an empty value.
    """
    v = _str(raw)
    if not v:
        return None
    if not re.match(r"^\d+(?:\.0+)?$", v):
        return ValidationRejection(code="duration_not_a_number", reason_human=_DURATION_NUMBERS_ONLY)
    n = float(v)
    if n % 1 != 0:
        return ValidationRejection(code="duration_not_whole", reason_human=_DURATION_NUMBERS_ONLY)
    i = int(n)
    if i < 1:
        return ValidationRejection(code="duration_too_short", reason_human=_DURATION_MIN_1)
    if i > 24:
        return ValidationRejection(code="duration_too_long", reason_human=_DURATION_MAX_24)
    return None


def _v_time_hm24_optional(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return None
    if not _HM24.match(v):
        return ValidationRejection(code="time_hm_invalid", reason_human=_TIME_HM_INVALID,
                                   suggested_fix="Use HH:mm format, e.g. 09:30 or 14:00.")
    return None


def _v_multi_enum_required(raw: Any, _state: Any) -> ValidationRejection | None:
    lst = _list(raw)
    if not lst:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    return None


def _v_text250_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    r = _required(v)
    if r:
        return r
    return _max_len(v, 250, "text_too_long")


def _v_text250_optional(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return None
    return _max_len(v, 250, "text_too_long")


def _v_text100_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    r = _required(v)
    if r:
        return r
    return _max_len(v, 100, "text_too_long")


def _v_text50_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    r = _required(v)
    if r:
        return r
    return _max_len(v, 50, "text_too_long")


def _v_text25_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    r = _required(v)
    if r:
        return r
    return _max_len(v, 25, "text_too_long")


def _v_secondary_diagnosis(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return None
    mn = _min_len(v, 5, "secondary_diagnosis_too_short")
    if mn:
        return mn
    return _max_len(v, 250, "secondary_diagnosis_too_long")


def _v_allergy_description(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    r = _required(v)
    if r:
        return r
    mn = _min_len(v, 5, "description_too_short")
    if mn:
        return mn
    return _max_len(v, 250, "description_too_long")


def _v_purpose(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    r = _required(v)
    if r:
        return r
    mn = _min_len(v, 5, "purpose_too_short")
    if mn:
        return mn
    return _max_len(v, 100, "purpose_too_long")


def _v_notes_optional(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return None
    mn = _min_len(v, 5, "notes_too_short")
    if mn:
        return mn
    return _max_len(v, 100, "notes_too_long")


def _v_medical_year(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return None
    try:
        yr = int(v)
        current = date.today().year
        if yr < 1900 or yr > current:
            return ValidationRejection(code="year_out_of_range",
                                       reason_human=f"Year must be between 1900 and {current}")
    except ValueError:
        return ValidationRejection(code="year_invalid", reason_human=_FIELD_REQUIRED)
    return None


def _v_support_description(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return None
    mn = _min_len(v, 5, "description_too_short")
    if mn:
        return mn
    return _max_len(v, 255, "description_too_long")


# ── Staff-specific validators ─────────────────────────────────────────────────

def _v_text10_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    r = _required(v)
    if r:
        return r
    return _max_len(v, 10, "text_too_long")


def _v_text12_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    r = _required(v)
    if r:
        return r
    return _max_len(v, 12, "text_too_long")


def _v_text500_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    r = _required(v)
    if r:
        return r
    return _max_len(v, 500, "text_too_long")


def _v_bsb(raw: Any, _state: Any) -> ValidationRejection | None:
    # Strip spaces/hyphens so "062-000" and "062 000" both pass
    v = re.sub(r"[\s\-]", "", _str(raw))
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    if not _BSB_RE.match(v):
        return ValidationRejection(
            code="bsb_invalid",
            reason_human=_BSB_INVALID,
            suggested_fix="Your BSB is the 6-digit number on your bank statement, e.g. 062000.",
        )
    return None


def _v_super_abn(raw: Any, _state: Any) -> ValidationRejection | None:
    v = re.sub(r"\D", "", _str(raw))
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    if not _ABN_RE.match(v):
        return ValidationRejection(
            code="abn_invalid",
            reason_human=_ABN_INVALID,
            suggested_fix="The ABN is printed on your super fund statements, e.g. 65714394898.",
        )
    return None


def _v_boolean_required(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _fv(raw)
    if v is None or (isinstance(v, str) and not v.strip()):
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    if isinstance(v, bool):
        return None
    if isinstance(v, str) and v.lower() in ("true", "false", "yes", "no"):
        return None
    return ValidationRejection(
        code="boolean_invalid",
        reason_human="Please answer yes or no.",
        suggested_fix="Please answer yes or no.",
    )


def _v_languages_spoken(raw: Any, _state: Any) -> ValidationRejection | None:
    lst = _list(raw)
    if not lst:
        v = _str(raw)
        if not v:
            return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
        return None
    for item in lst:
        if isinstance(item, str) and len(item) > 50:
            return ValidationRejection(
                code="language_item_too_long",
                reason_human=_at_most(50),
                suggested_fix="Each language name must be 50 characters or fewer.",
            )
    return None


def _v_doc_expiry_future(raw: Any, _state: Any) -> ValidationRejection | None:
    v = _str(raw)
    if not v:
        return ValidationRejection(code="required", reason_human=_FIELD_REQUIRED)
    try:
        expiry = date.fromisoformat(v)
    except ValueError:
        return ValidationRejection(
            code="expiry_invalid_format",
            reason_human=_EXPIRY_NOT_FUTURE,
            suggested_fix="Use YYYY-MM-DD format, e.g. 2028-06-01.",
        )
    if expiry <= date.today():
        return ValidationRejection(
            code="expiry_not_future",
            reason_human=_EXPIRY_NOT_FUTURE,
            suggested_fix="The document expiry date must be a future date.",
        )
    return None


# ── Field rules table ─────────────────────────────────────────────────────────
# Key: (section_id, field_id) → validator(raw_value, state) → ValidationRejection | None
_RULES: dict[tuple[str, str], Callable[[Any, Any], ValidationRejection | None]] = {
    # Step 1 — Personal Information
    ("basics", "full_name"):          _v_full_name,
    ("basics", "email"):              _v_email_standard_required,
    ("basics", "phone"):              _v_phone_au_required,
    ("basics", "date_of_birth"):      _v_dob,
    ("basics", "gender"):             _v_gender_required,
    # about_me: required (≤250 chars). Flutter is law — the participant flow
    # requires this field; reconciled 2026-05-12 by Agent 03B.
    ("basics", "about_me"):           _v_text250_required,
    ("basics", "preferred_language"): _v_preferred_language,
    # interpreter_required: boolean yes/no (Flutter ships a toggle). Accepts
    # Python bool or "true"/"false"/"yes"/"no" (case-insensitive).
    ("basics", "interpreter_required"): _v_boolean_required,
    ("basics", "interpreter_language"): _v_text250_optional,
    ("home_address", "address"):      _v_text_required,
    ("home_address", "state"):        _v_au_state,
    ("home_address", "city"):         _v_text_required,
    ("home_address", "zip_code"):     _v_postcode,
    ("service_address", "address"):   _v_text250_optional,
    ("service_address", "state"):     _v_au_state,
    ("service_address", "city"):      _v_text_required,
    ("service_address", "zip_code"):  _v_postcode,
    ("emergency_contacts", "name"):   _v_text25_required,
    ("emergency_contacts", "relation"): _v_text_required,
    ("emergency_contacts", "email"):  _v_email_required,
    ("emergency_contacts", "phone"):  _v_phone_au_required,

    # Step 2 — Participant Requirements
    ("requirements", "cultural_considerations"): _v_text250_required,
    ("requirements", "most_important"):          _v_text250_required,
    ("requirements", "goals"):                   _v_text250_required,
    ("requirements", "hobbies_interests"):       _v_text250_required,
    ("requirements", "mode_of_communication"):   _v_multi_enum_required,
    ("requirements", "style_of_communication"):  _v_multi_enum_required,
    ("morning_routine", "description"):          _v_text_required,
    ("morning_routine", "time"):                 _v_time_hm24_optional,
    ("evening_routine", "description"):          _v_text_required,
    ("evening_routine", "time"):                 _v_time_hm24_optional,

    # Step 3 — NDIS Plan Details
    ("plan_info", "ndis_number"):    _v_ndis_number,
    ("plan_info", "plan_start"):     _v_text_required,
    ("plan_info", "plan_end"):       _v_plan_end,
    ("plan_info", "plan_management"): _v_plan_management,
    ("plan_info", "plan_manager"):   _v_plan_manager_conditional,
    ("plan_info", "contact_email"):  _v_email_conditional,
    ("plan_info", "billing_email"):  _v_email_conditional,
    ("ndis_goals", "goal"):          _v_text250_required,
    ("support_coordinator", "coordinator_name"):  _v_text50_required,
    ("support_coordinator", "coordinator_email"): _v_email_standard_required,
    ("allocated_funding", "daily_living"):          _v_amount_optional,
    ("allocated_funding", "social_community"):       _v_amount_optional,
    ("allocated_funding", "support_coordination"):   _v_amount_optional,
    ("allocated_funding", "improved_daily_living"):  _v_amount_optional,
    ("schedule_of_supports", "support_name"):       _v_text100_required,
    ("schedule_of_supports", "support_category"):   _v_text_required,
    ("schedule_of_supports", "description"):        _v_support_description,
    ("schedule_of_supports", "frequency"):          _v_text_required,
    # Schema declares duration_hours as required: false — use the optional variant.
    ("schedule_of_supports", "duration_hours"):     _v_duration_optional,
    ("schedule_of_supports", "days"):               _v_multi_enum_required,
    ("schedule_of_supports", "start_time"):         _v_time_hm24_optional,
    ("schedule_of_supports", "end_time"):           _v_time_hm24_optional,

    # ── Staff Step 1 — Basic Profile (section_id: staff_basics) ─────────────────
    ("staff_basics", "full_name"):               _v_full_name,
    ("staff_basics", "phone"):                   _v_phone_au_required,
    ("staff_basics", "address"):                 _v_text100_required,
    ("staff_basics", "state"):                   _v_au_state,
    ("staff_basics", "city"):                    _v_text25_required,
    ("staff_basics", "zip_code"):                _v_postcode,
    ("staff_basics", "gender"):                  _v_text10_required,
    ("staff_basics", "cultural_background"):     _v_text50_required,
    ("staff_basics", "languages_spoken"):        _v_languages_spoken,
    ("staff_basics", "interpreter_required"):    _v_boolean_required,

    # ── Staff Step 2 — Experience ─────────────────────────────────────────────
    ("staff_experience", "experience"):          _v_text500_required,

    # ── Staff Step 3 — Document expiry (hasExpiry docs) ──────────────────────
    # Used when tools.py routes a document expiry field through validate_field.
    ("staff_documents", "expires_at"):           _v_doc_expiry_future,

    # ── Staff Step 4 — Banking Details ───────────────────────────────────────
    ("staff_banking", "bank_name"):              _v_text50_required,
    ("staff_banking", "account_holder_name"):    _v_text50_required,
    ("staff_banking", "bsb"):                    _v_bsb,
    ("staff_banking", "account_number"):         _v_text12_required,
    ("staff_banking", "super_fund_name"):        _v_text50_required,
    ("staff_banking", "super_fund_abn"):         _v_super_abn,
    ("staff_banking", "member_number"):          _v_text50_required,

    # Step 5 — Medical Information
    ("medical_overview", "primary_diagnosis"):   _v_text250_required,
    ("medical_overview", "secondary_diagnosis"): _v_secondary_diagnosis,
    ("medical_overview", "primary_doctor"):      _v_text50_required,
    ("medical_overview", "doctor_phone"):        _v_phone_au_optional,
    ("allergies", "title"):       _v_text25_required,
    ("allergies", "description"): _v_allergy_description,
    ("medications", "medication"): _v_text50_required,
    ("medications", "dosage"):     _v_text50_required,
    ("medications", "frequency"):  _v_text50_required,
    ("medications", "purpose"):    _v_purpose,
    ("medications", "notes"):      _v_notes_optional,
    ("medical_history", "title"):       _v_text25_required,
    ("medical_history", "year"):        _v_medical_year,
    ("medical_history", "description"): _v_allergy_description,
    ("mobility", "mobility_status"):      _v_text_required,
    ("mobility", "support_requirements"): _v_text250_required,
}


def validate_field(
    section_id: str,
    field_id: str,
    value: Any,
    *,
    repeatable_index: int | None = None,
    state: Any = None,
    field_spec: Any = None,
) -> ValidationRejection | None:
    """Return None if valid, ValidationRejection if the rule fires.

    Unknown (section, field) pairs return None — drift detection is handled
    by tools.py which logs unknown_field_attempt before calling this.

    Pass ``field_spec`` (a FieldSpec instance) to enable options enforcement
    for multi_enum fields — introduced in V3/S5. Backward-compatible: when
    omitted (None) the options check is skipped and behaviour is identical to
    the previous implementation.
    """
    fn = _RULES.get((section_id, field_id))
    if fn is None:
        return None
    rejection = fn(value, state)
    if rejection is not None:
        return rejection
    # Options check for multi_enum fields (V3/S5)
    if (
        field_spec is not None
        and getattr(field_spec, "type", None) == "multi_enum"
        and getattr(field_spec, "options", None)
    ):
        lst = _list(value)
        allowed = [o.lower() for o in field_spec.options]
        bad = [item for item in lst if item.lower() not in allowed]
        if bad:
            examples = ", ".join(f'"{o}"' for o in field_spec.options[:3])
            return ValidationRejection(
                code="enum_invalid",
                reason_human=(
                    f"That option isn't available. Please choose from the list — "
                    f"for example: {examples}."
                ),
                suggested_fix=f"Valid options: {', '.join(field_spec.options)}",
                allowed_values=list(field_spec.options),
            )
    return None
