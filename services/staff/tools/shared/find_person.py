"""find_person — entity resolver across BOTH client and staff lists.

Solves the "Sarah" problem: "tell me about Sarah" could be a client, staff,
or support worker. This tool searches both lists, returns type-tagged matches.
If multiple match, the LLM should follow up with clarify_with_user.
"""
import json
import re
import sys

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from bedrock_client import call_bedrock
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


def _safe_get(record, *keys):
    if not isinstance(record, dict):
        return None
    for k in keys:
        v = record.get(k)
        if v:
            return v
    return None


def _full_name(record):
    if not isinstance(record, dict):
        return ""
    name = _safe_get(record, "name", "fullName", "full_name")
    if name:
        return str(name)
    first = _safe_get(record, "firstName", "first_name") or ""
    last = _safe_get(record, "lastName", "last_name") or ""
    return f"{first} {last}".strip()


def _build_directory(stripped, kind):
    """Build a compact directory from a stripped list response."""
    records = []
    if isinstance(stripped, dict):
        for key in ("clients", "staff", "items", "rows", "list", "records"):
            if isinstance(stripped.get(key), list):
                records = stripped[key]
                break
    elif isinstance(stripped, list):
        records = stripped

    directory = []
    for r in records:
        if not isinstance(r, dict):
            continue
        directory.append({
            "id": _safe_get(r, "id", "_id", "clientId", "staffId"),
            "name": _full_name(r),
            "email": _safe_get(r, "email", "emailAddress"),
            "ndis": _safe_get(r, "ndisNumber", "ndis_number"),
            "type": kind,
        })
    return directory


def _fetch_clients_dir(search_query=None):
    """Fetch the client directory.

    If `search_query` is provided AND looks like a name (not a UUID), pass it
    as the `search` query param so the backend filters by first/last/preferred
    name — much faster and more accurate than pulling the full list. UUID-like
    queries fall back to the full list (the backend search expects names).
    """
    path = "/organization/client/list/all-clients"
    query_params = {}
    if search_query:
        q = search_query.strip()
        # Only use search for name-like queries — UUIDs are matched by ID downstream
        looks_like_uuid = len(q) >= 30 and "-" in q
        if not looks_like_uuid:
            query_params["search"] = q
    raw = call_target_api(
        method="GET",
        url=construct_api_url(path, {}),
        query_params=query_params,
    )
    if isinstance(raw, dict) and raw.get("error"):
        return []
    stripped = strip_api_response(path, raw, verbose=VERBOSE)
    return _build_directory(stripped, "client")


def _fetch_staff_dir(search_query=None):
    """Fetch the staff directory.

    Uses the persona-appropriate endpoint:
      - admin     → /organization/staff/get-all-staff-members
      - non-admin → /organization-member/team/get-all-staff-members

    Both accept `?search=<name>` for case-insensitive name filtering at the
    backend (faster + more accurate than fetching all and matching locally).
    UUID-like queries fall back to the full list.
    """
    user_type = (user_context.get("user_type") or "").lower()
    if user_type == "admin":
        path = "/organization/staff/get-all-staff-members"
    else:
        path = "/organization-member/team/get-all-staff-members"

    query_params = {}
    if search_query:
        q = search_query.strip()
        looks_like_uuid = len(q) >= 30 and "-" in q
        if not looks_like_uuid:
            query_params["search"] = q

    raw = call_target_api(
        method="GET",
        url=construct_api_url(path, {}),
        query_params=query_params,
    )
    if isinstance(raw, dict) and raw.get("error"):
        return []
    stripped = strip_api_response(path, raw, verbose=VERBOSE)
    return _build_directory(stripped, "staff")


def _llm_match(query, directory):
    """Use the LLM to find the best matches in the directory."""
    if not directory:
        return []

    system_prompt = (
        "Given a user's query (likely a person's name, partial name, email, or NDIS "
        "number) and a directory of people, return the matching entries.\n\n"
        "Return JSON ONLY: {\"matches\": [{\"id\": \"<id>\", \"type\": \"client|staff\", "
        "\"match_reason\": \"<brief>\"}]}\n\n"
        "Match on: name (full/partial/case-insensitive), email, NDIS number, "
        "explicit ID. Include ALL plausible matches (up to 10). If nothing matches, "
        "return {\"matches\": []}."
    )

    messages = [{
        "role": "user",
        "content": [{
            "text": f"Query: {query}\n\nDirectory:\n{json.dumps(directory, indent=2)[:30000]}"
        }],
    }]

    response = call_bedrock(messages, system_prompt, use_guardrail=False)
    if not response:
        return []

    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            decision = json.loads(match.group())
            return decision.get("matches", []) or []
    except Exception as e:
        if VERBOSE:
            print(f"[find_person] LLM parse failed: {e}", file=sys.stderr)
    return []


def _run(inputs):
    query = (inputs or {}).get("query", "").strip()
    type_filter = (inputs or {}).get("type", "auto").lower()

    if not query:
        return ToolResult(error="Missing required input: query (person name/email/NDIS#).")

    if VERBOSE:
        print(f"[find_person] query={query!r} type_filter={type_filter}", file=sys.stderr)

    # Build the combined directory. Pass query as search hint to BOTH
    # endpoints so the backend can pre-filter by name (faster, more accurate).
    directory = []
    if type_filter in ("auto", "client"):
        directory.extend(_fetch_clients_dir(search_query=query))
    if type_filter in ("auto", "staff", "support_worker"):
        directory.extend(_fetch_staff_dir(search_query=query))

    if not directory:
        return ToolResult(
            data={"matches": []},
            next_hint=(
                "No directory data available — the user may not have access to "
                "client/staff lists, or there are simply no records yet."
            ),
        )

    if len(directory) == 1:
        matches = [{
            "id": directory[0].get("id"),
            "type": directory[0].get("type"),
            "match_reason": "Only backend search result",
        }]
    else:
        matches = _llm_match(query, directory)

    # Enrich matches with full directory records (id, name, email, type)
    enriched = []
    seen = set()
    for m in matches:
        mid = m.get("id")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        for d in directory:
            if d.get("id") == mid:
                enriched.append({
                    "id": d["id"],
                    "name": d["name"],
                    "email": d.get("email"),
                    "ndis": d.get("ndis"),
                    "type": d["type"],
                    "match_reason": m.get("match_reason"),
                })
                break

    hint = None
    if len(enriched) == 0:
        hint = (
            f"No matches for '{query}'. Tell the user politely and suggest they "
            "check the spelling or try 'list all clients' / 'list all staff'."
        )
    elif len(enriched) == 1:
        hint = (
            f"Exactly one match: {enriched[0]['name']} ({enriched[0]['type']}). "
            f"Call get_client_details if type=client, otherwise return the basic info."
        )
    else:
        hint = (
            f"Multiple matches ({len(enriched)}). Use clarify_with_user to ask "
            "which person they meant. List names + types in the question."
        )

    return ToolResult(
        data={"query": query, "matches": enriched, "count": len(enriched)},
        next_hint=hint,
    )


TOOL = ToolSpec(
    name="find_person",
    description=(
        "Find a person (client OR staff OR support worker) by name, email, NDIS number, "
        "or partial match. Searches BOTH the client directory AND the staff directory "
        "simultaneously and returns type-tagged matches. Use whenever the user mentions a "
        "name without explicit context: 'tell me about Sarah', 'Tanishq details', 'find "
        "John Doe'. If multiple matches, follow up with clarify_with_user."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Name, partial name, email, or NDIS number to search for.",
            },
            "type": {
                "type": "string",
                "enum": ["auto", "client", "staff", "support_worker"],
                "description": (
                    "Search scope. 'auto' (default) searches both client and staff lists. "
                    "Use 'client' or 'staff' only when the user explicitly says so."
                ),
            },
        },
        "required": ["query"],
    },
    run=_run,
)
