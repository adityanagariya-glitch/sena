"""list_my_organizations — list organisations linked to the logged-in owner."""
import sys

from config import VERBOSE
from api_router import call_target_api, construct_api_url
from tools.base import ToolSpec, ToolResult


def _strip_organizations(raw):
    data = raw.get("data") if isinstance(raw, dict) else {}
    orgs = data.get("organizations") if isinstance(data, dict) else []
    if not isinstance(orgs, list):
        orgs = []

    organizations = []
    for org in orgs:
        if not isinstance(org, dict):
            continue
        organizations.append({
            "id": org.get("id"),
            "business_name": org.get("businessName") or org.get("business_name"),
        })

    return {
        "total": len(organizations),
        "organizations": organizations,
    }


def _run(inputs):
    path = "/organization/get-all-organizaions"

    if VERBOSE:
        print("[list_my_organizations] fetching owner organisations", file=sys.stderr)

    raw = call_target_api(
        method="GET",
        url=construct_api_url(path, {}),
        query_params={},
    )

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    return ToolResult(data=_strip_organizations(raw), meta={"path": path})


TOOL = ToolSpec(
    name="list_my_organizations",
    description=(
        "List organisations linked to the logged-in owner. Calls "
        "/organization/get-all-organizaions and returns organisation IDs and "
        "business names. Use for: 'my organisations', 'my organizations', "
        "'which organisations do I own', 'list my orgs', 'show owner "
        "organisations'."
    ),
    input_schema={"type": "object", "properties": {}},
    run=_run,
)
