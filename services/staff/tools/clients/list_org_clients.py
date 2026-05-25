"""list_org_clients — ADMIN ONLY: list every client across the entire org.

Uses /organization/client/list/all-clients (no pagination).
"""
import sys

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


def _run(inputs):
    user_type = (user_context.get("user_type") or "").lower()
    if user_type != "admin":
        return ToolResult(error="This tool is admin-only.")

    if VERBOSE:
        print("[list_org_clients] admin requesting full client list", file=sys.stderr)

    path = "/organization/client/list/all-clients"
    url = construct_api_url(path, {})
    raw = call_target_api(method="GET", url=url, query_params={})

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    stripped = strip_api_response(path, raw, verbose=VERBOSE)
    return ToolResult(data=stripped, meta={"path": path})


TOOL = ToolSpec(
    name="list_org_clients",
    description=(
        "ADMIN ONLY. List ALL clients across the entire organisation (no pagination). "
        "Use for: 'all clients in the org', 'every client', 'show me the full client "
        "list', 'how many clients total'. NOT for individual lookups — use find_person "
        "or get_client_details for specific clients."
    ),
    input_schema={"type": "object", "properties": {}},
    run=_run,
)
