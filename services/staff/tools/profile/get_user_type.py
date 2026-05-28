"""get_user_type — authoritative "who is this user" lookup via /auth/user-type.

Calls the backend's canonical user-type endpoint and refreshes user_context so
every persona-based decision (which shift/profile endpoint to hit, what APIs are
in scope, admin-only gating) uses the real values instead of role-name guessing.
"""
import sys

from config import VERBOSE
from state import user_context, apply_user_type_context
from api_router import call_target_api, construct_api_url
from tools.base import ToolSpec, ToolResult


def _run(inputs):
    url = construct_api_url("/auth/user-type", {})
    raw = call_target_api(method="GET", url=url)

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from /auth/user-type: {raw.get('error')}",
            meta={"status_code": raw.get("status_code")},
        )

    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return ToolResult(error="No user-type data returned by /auth/user-type.")

    # Keep user_context authoritative + fresh for the rest of this turn.
    apply_user_type_context(data)

    if VERBOSE:
        print(f"[get_user_type] {data} -> user_type={user_context.get('user_type')}", file=sys.stderr)

    return ToolResult(
        data={
            "userType": data.get("userType"),
            "staffType": data.get("staffType"),
            "organizationType": data.get("organizationType"),
            "isISW": bool(data.get("isISW")),
            "isSupportWorker": bool(data.get("isSupportWorker")),
            "resolved_role": user_context.get("user_type"),
        }
    )


TOOL = ToolSpec(
    name="get_user_type",
    description=(
        "Determine WHO the logged-in user is from the authoritative backend "
        "endpoint (GET /auth/user-type). Returns userType (superAdmin, lister, "
        "serviceProvider, organizationMember, client, visitor), plus staffType "
        "(support_worker / in_office / all), organizationType (organization / "
        "independent_support_worker), and the convenience flags isISW and "
        "isSupportWorker. Use when you need to confirm the user's exact role/"
        "context or when persona-dependent routing matters. Refreshes the stored "
        "user context. For a quick local answer with no API call, prefer my_profile."
    ),
    input_schema={"type": "object", "properties": {}},
    run=_run,
)
