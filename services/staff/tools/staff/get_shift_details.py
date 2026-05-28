"""get_shift_details — full details for ONE specific shift by ID.

Persona routing (matches the SENA UI's view-shift endpoint per role):
- ISW                                  → /mobile/isw-shift/view-shift/{id}
- support worker (mobile / field)      → /mobile/staff-shift/view-shift/{id}
- client / participant                 → /mobile/client-shift/view-shift/{id}
- admin                                → /organization/shift/details/{id}
- other org members                    → /organization-member/shift/details/{id}

Each "view-shift" mobile endpoint returns:
- core shift fields (title, status, date, times, location, agenda, notes)
- clients array (with participantId)
- supportWorkers array (with participantId)
- healthProfessionals array
- duration in minutes
- participantId for acknowledging the shift
"""
import sys

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


def _pick_path(shift_id):
    """Pick the right view-shift endpoint for the user's persona.

    Driven by the canonical context from /auth/user-type (stored in user_context
    by apply_user_type_context): user_type_raw, is_isw, is_support_worker,
    staff_type. Falls back to the legacy normalised `user_type`/`roles` if the
    canonical fields aren't populated.
    """
    user_type_raw = (user_context.get("user_type_raw") or "").strip()
    legacy = (user_context.get("user_type") or "").lower()
    staff_type = (user_context.get("staff_type") or "").lower()
    roles = [r.lower() for r in (user_context.get("roles") or [])]
    is_isw = bool(user_context.get("is_isw"))
    is_support_worker = bool(user_context.get("is_support_worker"))

    # ISW (independent support worker) — mobile ISW endpoint
    if is_isw or legacy == "isw":
        return "/mobile/isw-shift/view-shift/{id}"
    # Client / participant / guardian-visitor — mobile client endpoint
    if user_type_raw in ("client", "visitor") or legacy in ("client", "guardian") or "guardian" in roles:
        return "/mobile/client-shift/view-shift/{id}"
    # Support worker (field / mobile) — mobile staff endpoint
    if is_support_worker or staff_type == "support_worker":
        return "/mobile/staff-shift/view-shift/{id}"
    # Admin / super admin / org owner — full organisation endpoint
    if legacy == "admin" or user_type_raw in ("superAdmin", "serviceProvider"):
        return "/organization/shift/details/{id}"
    # Default: in-office staff / other org members
    return "/organization-member/shift/details/{id}"


def _run(inputs: dict | None) -> ToolResult:
    shift_id = (inputs or {}).get("shift_id")
    if not shift_id:
        return ToolResult(error="Missing required input: shift_id.")

    path = _pick_path(shift_id)
    url = construct_api_url(path, {"id": shift_id})

    if VERBOSE:
        print(f"[get_shift_details] shift_id={shift_id} path={path}", file=sys.stderr)

    raw = call_target_api(method="GET", url=url)

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    # Bypass stripper — LLM extracts fields directly from raw JSON.
    return ToolResult(
        data=raw,
        meta={"path": path, "shift_id": shift_id},
    )


TOOL = ToolSpec(
    name="get_shift_details",
    description=(
        "Retrieve COMPLETE shift details: title, participants (clients), support workers, "
        "health professionals, location, agenda, notes, and all assignment information. "
        "Use when:\n"
        "- User asks about a specific shift by ID\n"
        "- User asks 'who am I working with?' / 'with whom?' / 'who's assigned?' — "
        "detail endpoint has complete assignment data\n"
        "- You need to verify or clarify shift assignments/participants"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shift_id": {
                "type": "string",
                "description": "Shift UUID/ID from a prior listing.",
            }
        },
        "required": ["shift_id"],
    },
    run=_run,
)
