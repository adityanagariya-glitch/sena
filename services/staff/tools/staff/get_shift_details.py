"""get_shift_details — full details for ONE specific shift by ID.

Persona routing:
- ISW                                  → /isw/shift/core-details/{id}
- support worker (staff_type)          → /mobile/staff-shift/view-shift/{id}
- admin                                → /organization/shift/details/{id}
- other org members                    → /organization-member/shift/details/{id}
"""
import sys

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


def _pick_path(shift_id):
    user_type = (user_context.get("user_type") or "").lower()
    staff_type = (user_context.get("staff_type") or "").lower()

    if user_type == "isw":
        return "/isw/shift/core-details/{id}"
    if staff_type == "support_worker":
        return "/mobile/staff-shift/view-shift/{id}"
    if user_type == "admin":
        return "/organization/shift/details/{id}"
    # Default: in-office staff / other org members
    return "/organization-member/shift/details/{id}"


def _run(inputs):
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
        "Get full details for ONE specific shift by ID. Use when the user has "
        "already seen a shift listing and asks for more info on a specific one "
        "('show me that shift', 'details on shift X')."
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
