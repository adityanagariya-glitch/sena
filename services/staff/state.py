"""Shared mutable state across modules.

These are mutable containers (dict, list) so `from state import user_context`
gives every module the same reference — mutations are visible everywhere.

`jwt_token` is intentionally NOT here. It's reassigned (not mutated) via
`global jwt_token`, so it must live in the same module that reassigns it
(auth.py) — otherwise other modules would see a stale snapshot.

API loading is section-based:
  - STAFF_APIS  → shifts, payroll, allowances, staff-shift, isw, org-shift
  - CLIENT_APIS → client profiles, agreements, documents, guardian/visitor views
  - COMMON_APIS → roles, profiles, org lookups (shared across both sections)

Use `get_apis_for_user()` to fetch the section-relevant API set for the current
logged-in user. AVAILABLE_APIS is kept as the union for backward compatibility.
"""
import json
import sys
import hashlib
from pathlib import Path
from typing import TypedDict
from difflib import SequenceMatcher

_api_dir = Path(__file__).parent


class UserTypeResponse(TypedDict, total=False):
    """Schema for GET /auth/user-type response."""
    userType: str
    isISW: bool
    isSupportWorker: bool
    staffType: str | None
    organizationType: str | None


# Section-specific API definitions
COMMON_APIS = json.load(open(_api_dir / 'common_apis.json'))
CLIENT_APIS = json.load(open(_api_dir / 'clients_apis.json'))
STAFF_APIS = json.load(open(_api_dir / 'staff_apis.json'))

# Backward-compat: full merged list (every API loaded at startup).
AVAILABLE_APIS = COMMON_APIS + CLIENT_APIS + STAFF_APIS

# User profile populated by the auth flow.
user_context = {
    "user_id": None,
    "organization_id": None,
    "roles": [],
    "user_type": None,        # legacy normalised value (admin/staff/isw/client/guardian/...)
    # Canonical context from GET /auth/user-type (authoritative source of truth).
    "user_type_raw": None,    # e.g. organizationMember / serviceProvider / client / visitor / superAdmin / lister
    "staff_type": None,       # support_worker / in_office / all / None
    "organization_type": None,  # organization / independent_support_worker / None
    "is_isw": False,
    "is_support_worker": False,
    "email": None,
    "authenticated": False,
    # Set by the frontend (lat/lng → IANA tz). Code reading this should fall
    # back to "Australia/Sydney" when None — see current_timezone() below.
    # See time_plan.md for the full resolution chain.
    "lat": None,
    "lng": None,
    "timezone": None,
}


def current_timezone():
    """Return the user's IANA timezone for all date math.

    Resolution order:
      1. user_context["timezone"]           ← set by frontend (future)
      2. "Australia/Sydney"                  ← safe fallback for NDIS workers

    Never returns None. Use this everywhere instead of hardcoding a zone.
    When the frontend wires up lat/lng → tz resolution, no code changes here
    will be needed — callers just start picking up the right tz.
    """
    tz = (user_context.get("timezone") or "").strip()
    return tz or "Australia/Sydney"


# Australian IANA zones that observe daylight saving time. Stored once here so
# any module can ask "does the user's timezone observe DST" without hardcoding.
# zoneinfo handles the actual offset switch automatically (Apr / Oct each year)
# from IANA tzdata — we never adjust offsets manually.
DST_OBSERVING_ZONES = frozenset({
    "Australia/Sydney",      # NSW — AEST ↔ AEDT
    "Australia/Melbourne",   # VIC — AEST ↔ AEDT
    "Australia/Hobart",      # TAS — AEST ↔ AEDT
    "Australia/Adelaide",    # SA  — ACST ↔ ACDT (30-min offset)
    "Australia/Canberra",    # ACT — same rules as NSW
    "Australia/Lord_Howe",   # Lord Howe Island — 30-min DST shift
})


def timezone_observes_dst(tz_name=None):
    """True if the timezone observes daylight saving at any point in the year.
    Brisbane / Perth / Darwin → False. Sydney / Melbourne / Adelaide → True."""
    return (tz_name or current_timezone()) in DST_OBSERVING_ZONES


def timezone_dst_active_now(tz_name=None):
    """True if DST is currently in effect for the given (or current) timezone."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz_name = tz_name or current_timezone()
    try:
        offset = datetime.now(ZoneInfo(tz_name)).dst()
        return bool(offset and offset.total_seconds() != 0)
    except Exception:
        return False


def timezone_short_label(tz_name=None):
    """Friendly label for an IANA zone — e.g. 'Australia/Sydney' → 'Sydney'."""
    tz_name = tz_name or current_timezone()
    return tz_name.split('/')[-1].replace('_', ' ')

# In-memory fallback when AgentCore is disabled. Holds the last N turns of the
# current process only — lost on restart, but lets the chatbot work locally
# without provisioning AWS resources.
conversation_history = []


def get_apis_for_user(user_type=None, staff_type=None, roles=None):
    """Return the section-relevant APIs for the current user.

    Section mapping:
      - client / guardian users    → CLIENT_APIS + COMMON_APIS
      - admin / staff / isw users  → STAFF_APIS + CLIENT_APIS + COMMON_APIS
                                      (admins/staff manage both shifts AND clients)

    Falls back to AVAILABLE_APIS (everything) when user role is unknown.
    """
    if user_type is None:
        user_type = (user_context.get("user_type") or "").lower()
    else:
        user_type = (user_type or "").lower()

    if staff_type is None:
        staff_type = (user_context.get("staff_type") or "").lower()
    else:
        staff_type = (staff_type or "").lower()

    if roles is None:
        roles = [r.lower() for r in (user_context.get("roles") or [])]
    else:
        roles = [r.lower() for r in (roles or [])]

    # Client-facing personas: only see client + common APIs
    if user_type in ("client", "guardian") or "guardian" in roles:
        return CLIENT_APIS + COMMON_APIS

    # Staff-facing personas (admin, staff, isw, support_worker): see everything
    # they may need to operate on clients AND manage shifts/payroll
    if user_type in ("admin", "staff", "isw") or staff_type == "support_worker":
        return STAFF_APIS + CLIENT_APIS + COMMON_APIS

    # Unknown persona → everything (safe default; backend enforces access)
    return AVAILABLE_APIS


# ---- ALGO 1: Schema Fingerprinting (detects API structure changes) ----

EXPECTED_SCHEMA_FIELDS = {"userType", "isISW", "isSupportWorker", "staffType", "organizationType"}
REQUIRED_FIELDS = {"userType", "isISW", "isSupportWorker"}


def _compute_schema_fingerprint(data: dict) -> str | None:
    """Hash of actual response field names + types. Detects additions/removals/type changes."""
    if not isinstance(data, dict):
        return None
    keys = sorted(data.keys())
    types = ",".join(type(data[k]).__name__ for k in keys)
    fingerprint = hashlib.sha256(f"{keys}:{types}".encode()).hexdigest()[:8]
    return fingerprint


def _validate_schema(data: dict) -> tuple[bool, list[str], list[str]]:
    """Check API response schema. Returns (is_valid, missing_fields, extra_fields)."""
    if not isinstance(data, dict):
        return False, list(REQUIRED_FIELDS), []

    actual_fields = set(data.keys())
    missing = REQUIRED_FIELDS - actual_fields
    extra = actual_fields - EXPECTED_SCHEMA_FIELDS

    return len(missing) == 0, list(missing), list(extra)


# ---- ALGO 2: Fuzzy String Matching (detects userType renames) ----

KNOWN_USER_TYPES = {"superAdmin", "serviceProvider", "organizationMember", "client", "visitor", "lister"}


def _fuzzy_match_user_type(incoming_type: str | None, threshold: float = 0.8) -> tuple[str | None, float]:
    """Find closest known userType by similarity. Returns (matched_type, score) or (None, score)."""
    if not incoming_type:
        return None, 0.0

    if incoming_type in KNOWN_USER_TYPES:
        return incoming_type, 1.0

    matches = [
        (known, SequenceMatcher(None, incoming_type, known).ratio())
        for known in KNOWN_USER_TYPES
    ]
    matches.sort(key=lambda x: x[1], reverse=True)

    best_match, score = matches[0] if matches else (None, 0.0)
    return (best_match, score) if score >= threshold else (None, score)


# ---- END ALGOS ----


def _derive_legacy_user_type(user_type_raw: str | None, is_isw: bool, is_support_worker: bool) -> str:
    """Map canonical /auth/user-type userType to legacy value (admin/staff/isw/client/guardian/lister/unknown)."""
    ut = (user_type_raw or "").strip()
    match ut:
        case "superAdmin":
            return "admin"
        case "serviceProvider":
            return "isw" if is_isw else "admin"
        case "organizationMember":
            return "staff" if is_support_worker else "admin"
        case "client":
            return "client"
        case "visitor":
            return "guardian"
        case "lister":
            return "lister"
        case _:
            return "unknown"


def apply_user_type_context(data: UserTypeResponse | dict) -> bool:
    """Store canonical /auth/user-type response into user_context and derive legacy user_type.

    Applies two hardening algorithms:
    1. Schema Fingerprinting — detects API structure changes (field additions/removals)
    2. Fuzzy String Matching — detects userType value renames (isw → isw-worker)
    """
    if not isinstance(data, dict):
        return False

    # ALGO 1: Validate schema structure
    is_valid, missing, extra = _validate_schema(data)
    if missing:
        print(
            f"[SCHEMA_ERROR] Missing required fields: {missing}. "
            f"Expected schema: {REQUIRED_FIELDS}",
            file=sys.stderr,
        )
        return False
    if extra:
        print(
            f"[SCHEMA_WARNING] Extra fields in API response: {extra}. "
            f"Expected only: {EXPECTED_SCHEMA_FIELDS}",
            file=sys.stderr,
        )

    user_type_raw = data.get("userType", "").strip()
    staff_type = data.get("staffType")
    is_isw = bool(data.get("isISW"))
    is_support_worker = bool(data.get("isSupportWorker"))

    # ALGO 2: Fuzzy match userType in case of renames
    if user_type_raw and user_type_raw not in KNOWN_USER_TYPES:
        matched, score = _fuzzy_match_user_type(user_type_raw)
        if matched:
            print(
                f"[FUZZY_MATCH] userType '{user_type_raw}' matched to '{matched}' "
                f"(similarity={score:.2f}). API may have renamed the value.",
                file=sys.stderr,
            )
            user_type_raw = matched
        else:
            print(
                f"[FUZZY_MATCH_FAILED] userType '{user_type_raw}' has no close match (score={score:.2f}). "
                f"Proceeding with unknown role.",
                file=sys.stderr,
            )

    user_context["user_type_raw"] = user_type_raw
    if staff_type is not None:
        user_context["staff_type"] = staff_type
    user_context["organization_type"] = data.get("organizationType")
    user_context["is_isw"] = is_isw
    user_context["is_support_worker"] = is_support_worker
    user_context["user_type"] = _derive_legacy_user_type(user_type_raw, is_isw, is_support_worker)

    return True
