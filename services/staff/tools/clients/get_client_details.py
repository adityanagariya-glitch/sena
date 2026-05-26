"""get_client_details — full profile for one specific client by ID."""
import re
import sys

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _run(inputs):
    client_id = (inputs or {}).get("client_id")
    if not client_id:
        return ToolResult(error="Missing required input: client_id.")
    client_id = str(client_id).strip()

    if not _UUID_RE.match(client_id):
        return ToolResult(
            error="client_id must be a valid client UUID from a previous lookup.",
            next_hint=(
                "Do not guess client IDs. If the user gave a client name, call "
                "find_person(query=<name>, type='client') first, then call "
                "get_client_details with the UUID returned by that lookup."
            ),
            meta={"invalid_client_id": client_id},
        )

    user_type = (user_context.get("user_type") or "").lower()
    roles = [r.lower() for r in (user_context.get("roles") or [])]

    if "guardian" in roles or user_type == "guardian":
        path = "/mobile/visitor/clients/{clientId}"
        placeholders = {"clientId": client_id}
    elif "support_coordinator" in roles or "support coordinator" in " ".join(roles):
        path = "/organization/support-coordinator/client/{id}"
        placeholders = {"id": client_id}
    else:
        # admin / staff default
        path = "/organization/client/get/{id}"
        placeholders = {"id": client_id}

    if VERBOSE:
        print(f"[get_client_details] client_id={client_id} path={path}", file=sys.stderr)

    url = construct_api_url(path, placeholders)
    raw = call_target_api(method="GET", url=url, query_params={})

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    # Bypass stripper — LLM reads field names directly from the raw response.
    return ToolResult(data=raw, meta={"path": path, "client_id": client_id})


TOOL = ToolSpec(
    name="get_client_details",
    description=(
        "Get the FULL profile of one specific client by ID. Use when the user has already "
        "identified a specific client (via find_person or a previous listing) and wants "
        "details: 'tell me about client X', 'show client X profile', 'client X details', "
        "'her details', 'his profile', 'more about <name>'. Do NOT guess IDs from names; "
        "for a name, call find_person first and use the UUID it returns."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Client UUID/ID from a prior find_person or listing call.",
            }
        },
        "required": ["client_id"],
    },
    run=_run,
)
