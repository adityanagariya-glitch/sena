"""get_client_details — full profile for one specific client by ID.

Eager loading: fetches client profile + support workers + guardians in parallel,
so the LLM sees all related data immediately without requiring separate follow-up calls.
"""
import re
import sys

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult
from tools._common import parallel_fetch


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _run(inputs: dict | None) -> ToolResult:
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
    elif staff_type in ("support_worker", "isw") or user_type in ("staff", "isw"):
        # Support workers (including ISWs) use the mobile endpoint for their assigned clients
        path = "/mobile/visitor/clients/{clientId}"
        placeholders = {"clientId": client_id}
    elif "support_coordinator" in roles or "support coordinator" in " ".join(roles):
        path = "/organization/support-coordinator/client/{id}"
        placeholders = {"id": client_id}
    else:
        # admin / client default
        path = "/organization/client/get/{id}"
        placeholders = {"id": client_id}

    if VERBOSE:
        print(f"[get_client_details] client_id={client_id} path={path}", file=sys.stderr)

    # ---- EAGER LOADING: fetch client + support workers + guardians in parallel ----
    # Avoids the follow-up question "show me their support workers" by having the
    # data ready immediately. All three are typically small responses.
    fetchers = [
        {
            "label": "client",
            "url": construct_api_url(path, placeholders),
            "params": {},
        },
        {
            "label": "support_workers",
            "url": construct_api_url("/mobile/client/get-support-workers/{clientId}", {"clientId": client_id}),
            "params": {},
        },
        {
            "label": "guardians",
            "url": construct_api_url("/mobile/client/get-guardians/{clientId}", {"clientId": client_id}),
            "params": {},
        },
    ]
    
    results = parallel_fetch(fetchers, tool_name="get_client_details")
    
    raw = results.get("client", {})
    raw_workers = results.get("support_workers", {})
    raw_guardians = results.get("guardians", {})

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    # Bundle all related data so LLM sees complete context
    bundled = {
        "client_profile": raw,
        "support_workers": raw_workers if not isinstance(raw_workers, dict) or not raw_workers.get("error") else None,
        "guardians": raw_guardians if not isinstance(raw_guardians, dict) or not raw_guardians.get("error") else None,
        "_note": "Support workers and guardians are eagerly loaded and bundled with the profile. If the user asks follow-up questions about them, you already have the data — no need to call separate tools.",
    }
    
    return ToolResult(
        data=bundled,
        meta={
            "path": path,
            "client_id": client_id,
            "eager_loaded": ["support_workers", "guardians"],
        },
    )


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
