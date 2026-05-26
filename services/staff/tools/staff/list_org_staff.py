"""list_org_staff — list all staff/members in the organisation.

Endpoint picked by persona:
- admin     → /organization/staff/get-all-staff-members
- non-admin → /organization-member/team/get-all-staff-members

Both endpoints accept:
- `search` (string)    → case-insensitive name filter (backend-side)
- `staffType` (string) → "in_office" or "support_worker" (omit for all)
"""
import sys

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


def _run(inputs):
    inputs = inputs or {}
    search = (inputs.get("search") or "").strip()
    staff_type = (inputs.get("staff_type") or "").strip()

    user_type = (user_context.get("user_type") or "").lower()
    if user_type == "admin":
        path = "/organization/staff/get-all-staff-members"
    else:
        path = "/organization-member/team/get-all-staff-members"

    query_params = {}
    if search:
        query_params["search"] = search
    if staff_type and staff_type != "all":
        query_params["staffType"] = staff_type

    if VERBOSE:
        print(
            f"[list_org_staff] path={path} search={search!r} staff_type={staff_type!r}",
            file=sys.stderr,
        )

    url = construct_api_url(path, {})
    raw = call_target_api(method="GET", url=url, query_params=query_params)

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    stripped = strip_api_response(path, raw, verbose=VERBOSE)
    return ToolResult(
        data=stripped,
        meta={"path": path, "search": search, "staff_type": staff_type},
    )


TOOL = ToolSpec(
    name="list_org_staff",
    description=(
        "List staff/members in the organisation. PRIMARY TOOL for staff lookups. "
        "For admin users this calls /organization/staff/get-all-staff-members. "
        "For non-admin organisation members this calls /organization-member/team/"
        "get-all-staff-members. "
        "Use for: 'all staff', 'in-office staff', 'support workers', 'find Sarah "
        "in staff', 'show me the team'. Pass `search` to filter by name "
        "(backend does case-insensitive matching). Pass `staff_type` to filter "
        "by type (in_office or support_worker)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": (
                    "Optional: filter staff by name (case-insensitive, "
                    "first/last/preferred). USE THIS whenever the user mentions "
                    "a staff member's name."
                ),
            },
            "staff_type": {
                "type": "string",
                "description": (
                    "Optional: filter by staff type. 'in_office' for in-office "
                    "staff only, 'support_worker' for support workers only, "
                    "omit (or 'all') to return everyone."
                ),
                "enum": ["in_office", "support_worker", "all"],
            },
        },
    },
    run=_run,
)
