"""list_my_clients — list clients personally associated with the user.

- admin → /organization/client/my-clients (clients in their org)
- support worker → /mobile/visitor/clients (their assigned clients)
- guardian → /mobile/visitor/clients (their authorised clients)
"""
import sys

from config import VERBOSE
from state import user_context
from auth import has_auth_token
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult
from tools._common import parallel_fetch, dedup_by_id


def _run(inputs: dict | None) -> ToolResult:
    page = (inputs or {}).get("page") or 1
    limit = (inputs or {}).get("limit") or 50

    user_type = (user_context.get("user_type") or "").lower()
    staff_type = (user_context.get("staff_type") or "").lower()
    roles = [r.lower() for r in (user_context.get("roles") or [])]

    if VERBOSE:
        print(f"[list_my_clients] user_type={user_type} staff_type={staff_type}", file=sys.stderr)

    if not user_context.get("authenticated") or not has_auth_token():
        return ToolResult(
            error=(
                "User profile or backend session context is not loaded, so "
                "clients cannot be retrieved yet."
            ),
            next_hint=(
                "This is an internal context problem. Do not say the user "
                "needs to log in or authenticate. Tell them you hit a snag "
                "loading their SENA client list and ask them to try again in "
                "a moment."
            ),
            meta={"auth_context_missing": True},
        )

    # Client persona: they ARE the client — they don't have a list of "other clients".
    # Redirect with a friendly explanation instead of hitting a random endpoint.
    if user_type == "client":
        return ToolResult(
            data={"total": 0, "showing": 0, "clients": []},
            next_hint=(
                "The logged-in user IS a client/participant, not a coordinator. "
                "Tell them: 'You're set up as a participant — you don't have a list "
                "of other clients. Want me to show your own profile, your shifts, "
                "or look up a policy?'"
            ),
        )

    if user_type == "admin":
        path = "/organization/client/my-clients"
    elif "guardian" in roles or user_type == "guardian":
        path = "/mobile/visitor/clients"
    elif staff_type == "support_worker" or user_type == "staff":
        # ISW bridges support-worker and coordinator roles — call both endpoints
        # in parallel and merge so the user sees all their clients regardless of
        # which role they were assigned under.
        query_params = {"page": str(page), "limit": str(limit)}
        fetchers = [
            {
                "label": "visitor",
                "url": construct_api_url("/mobile/visitor/clients", {}),
                "params": query_params,
            },
            {
                "label": "coordinator",
                "url": construct_api_url("/organization-member/support-coordinator/my-clients", {}),
                "params": query_params,
            },
        ]
        par = parallel_fetch(fetchers, tool_name="list_my_clients")
        raw_visitor = par.get("visitor", {})
        raw_coord = par.get("coordinator", {})

        visitor_err = isinstance(raw_visitor, dict) and raw_visitor.get("error")
        coord_err = isinstance(raw_coord, dict) and raw_coord.get("error")

        if visitor_err and coord_err:
            return ToolResult(
                error=f"Both client sources failed: {raw_visitor.get('error')}",
                meta={
                    "status_code": raw_visitor.get("status_code"),
                    "paths": ["/mobile/visitor/clients", "/organization-member/support-coordinator/my-clients"],
                },
            )

        def _extract(raw):
            if not isinstance(raw, dict):
                return []
            data = raw.get("data", raw)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                inner = data.get("data", [])
                if isinstance(inner, list):
                    return inner
            return []

        clients_a = _extract(raw_visitor) if not visitor_err else []
        clients_b = _extract(raw_coord) if not coord_err else []
        merged = dedup_by_id(clients_a + clients_b, id_keys=("clientId", "id", "_id"))

        return ToolResult(
            data={"clients": merged, "total": len(merged)},
            meta={
                "paths": ["/mobile/visitor/clients", "/organization-member/support-coordinator/my-clients"],
                "visitor_count": len(clients_a),
                "coordinator_count": len(clients_b),
                "merged_total": len(merged),
            },
        )
    else:
        path = "/organization/client/my-clients"

    query_params = {"page": str(page), "limit": str(limit)}
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
        meta={"path": path, "query_params": query_params},
    )


TOOL = ToolSpec(
    name="list_my_clients",
    description=(
        "List the clients this user is personally associated with. For admins, returns "
        "clients in their organisation. For support workers/staff, returns their assigned "
        "clients. For guardians, returns clients they're authorised for. Use for: "
        "'my clients', 'clients i have', 'show clients', 'do i have any clients', "
        "'who are my clients'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "page": {"type": "integer", "description": "Page number, default 1", "minimum": 1},
            "limit": {"type": "integer", "description": "Records per page, default 50", "minimum": 1, "maximum": 200},
        },
    },
    run=_run,
)
