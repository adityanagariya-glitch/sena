"""get_client_guardians — guardian/family contacts for a specific client."""
import sys

from config import VERBOSE
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


def _run(inputs: dict | None) -> ToolResult:
    client_id = (inputs or {}).get("client_id")
    if not client_id:
        return ToolResult(error="Missing required input: client_id.")

    if VERBOSE:
        print(f"[get_client_guardians] client_id={client_id}", file=sys.stderr)

    path = "/organization/client/{clientId}/guardians"
    url = construct_api_url(path, {"clientId": client_id})
    raw = call_target_api(method="GET", url=url, query_params={})

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    stripped = strip_api_response(path, raw, verbose=VERBOSE)
    return ToolResult(data=stripped, meta={"path": path, "client_id": client_id})


TOOL = ToolSpec(
    name="get_client_guardians",
    description=(
        "Get the guardians/visitors authorised for a specific client. Use for: 'who are "
        "X's guardians', 'guardian list for X', 'family contacts for X', 'next of kin for X'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "client_id": {"type": "string"}
        },
        "required": ["client_id"],
    },
    run=_run,
)
