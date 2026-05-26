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
from pathlib import Path

_api_dir = Path(__file__).parent

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
    "user_type": None,
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
