"""list_org_clients — ADMIN ONLY: list organisation clients.

Keeps both client-list APIs:
- /organization/client/list             → paged, lightweight display/search
- /organization/client/list/all-clients → full unpaginated directory/cohort work
"""
import sys

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


def _run(inputs: dict | None) -> ToolResult:
    inputs = inputs or {}
    user_type = (user_context.get("user_type") or "").lower()
    if user_type != "admin":
        return ToolResult(error="This tool is admin-only.")

    mode = (inputs.get("mode") or "paged").strip().lower()
    page = inputs.get("page") or 1
    limit = inputs.get("limit") or 10
    search = (inputs.get("search") or "").strip()

    if mode not in ("paged", "all"):
        mode = "paged"

    if VERBOSE:
        print(
            f"[list_org_clients] mode={mode} page={page} limit={limit} search={search!r}",
            file=sys.stderr,
        )

    if mode == "all":
        path = "/organization/client/list/all-clients"
        query_params = {}
        if search:
            query_params["search"] = search
    else:
        path = "/organization/client/list"
        query_params = {"page": int(page), "limit": int(limit)}
        if search:
            query_params["search"] = search

    url = construct_api_url(path, {})
    raw = call_target_api(method="GET", url=url, query_params=query_params)

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    stripped = strip_api_response(path, raw, verbose=VERBOSE)
    return ToolResult(data=stripped, meta={"path": path, "query_params": query_params})


TOOL = ToolSpec(
    name="list_org_clients",
    description=(
        "ADMIN ONLY. List organisation clients. Use mode='paged' for normal display "
        "requests like 'client list' or 'show clients' — calls /organization/client/list "
        "with page/limit (default page=1, limit=10). Use mode='all' only when the user "
        "explicitly asks for every/all clients, total counts, or when another task needs "
        "the full directory — calls /organization/client/list/all-clients. For individual "
        "lookups by name, prefer find_person."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["paged", "all"],
                "description": (
                    "paged = lightweight /organization/client/list with page+limit. "
                    "all = full /organization/client/list/all-clients. Default paged."
                ),
            },
            "page": {
                "type": "integer",
                "description": "Page number for mode=paged. Default 1.",
                "minimum": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Records per page for mode=paged. Default 10.",
                "minimum": 1,
                "maximum": 100,
            },
            "search": {
                "type": "string",
                "description": "Optional client name search.",
            },
        },
    },
    run=_run,
)
