"""search_clients — server-side keyword + multi-filter client search.

Wraps GET /organization/client/search, the backend's LLM-friendly search
endpoint. Unlike filter_clients_by_criteria (which fetches EVERY client's full
profile and filters in-process), this pushes the work to the backend in a
single call — pass any combination of dimensions and the API returns matching
clients with pagination. All params are optional and AND-combined.

Use this as the DEFAULT for cohort/lookup queries that map onto the supported
dimensions (free text, gender, age range, diagnosis, mobility, medication,
language, location). Fall back to filter_clients_by_criteria only when you need
to match on profile content this endpoint does not index.

Example queries this handles:
  - "which clients under 25 need a wheelchair"  → maxAge=25, mobility=wheelchair
  - "clients with a peanut allergy on metformin" → search=peanut, medication=metformin
  - "find clients who need a walking stick"       → mobility=walking stick
  - "Arabic-speaking clients in Sydney aged 60+"  → language=arabic, location=Sydney, minAge=60
"""
import sys

from config import VERBOSE
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


_PATH = "/organization/client/search"

# Maps the tool's snake_case inputs → the API's query-param names (camelCase
# where the backend expects it, per the OpenAPI spec).
_PARAM_MAP = {
    "search": "search",
    "gender": "gender",
    "min_age": "minAge",
    "max_age": "maxAge",
    "diagnosis": "diagnosis",
    "mobility": "mobility",
    "medication": "medication",
    "language": "language",
    "location": "location",
}

_INT_PARAMS = {"min_age", "max_age"}


def _build_query_params(inputs: dict) -> dict:
    """Translate tool inputs into API query params, dropping empties."""
    query_params: dict = {}
    for tool_key, api_key in _PARAM_MAP.items():
        value = inputs.get(tool_key)
        if value is None:
            continue
        if tool_key in _INT_PARAMS:
            try:
                query_params[api_key] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            text = str(value).strip()
            if text:
                query_params[api_key] = text

    # Optional pagination passthrough.
    page = inputs.get("page")
    limit = inputs.get("limit")
    if page is not None:
        try:
            query_params["page"] = int(page)
        except (TypeError, ValueError):
            pass
    if limit is not None:
        try:
            query_params["limit"] = int(limit)
        except (TypeError, ValueError):
            pass

    return query_params


def _run(inputs: dict | None) -> ToolResult:
    inputs = inputs or {}
    query_params = _build_query_params(inputs)

    if not query_params:
        return ToolResult(
            error=(
                "Provide at least one filter (search, gender, min_age, max_age, "
                "diagnosis, mobility, medication, language, or location)."
            ),
            next_hint="Ask the user what they want to search clients by.",
        )

    if VERBOSE:
        print(f"[search_clients] query_params={query_params}", file=sys.stderr)

    url = construct_api_url(_PATH, {})
    raw = call_target_api(method="GET", url=url, query_params=query_params)

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {_PATH}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": _PATH},
        )

    stripped = strip_api_response(_PATH, raw, verbose=VERBOSE)
    return ToolResult(
        data=stripped,
        meta={"path": _PATH, "query_params": query_params},
    )


TOOL = ToolSpec(
    name="search_clients",
    description=(
        "Search organisation clients by keyword and/or structured filters in ONE "
        "fast backend call (GET /organization/client/search). PREFER this over "
        "filter_clients_by_criteria for cohort and lookup queries that fit the "
        "supported dimensions. All filters are optional and AND-combined, so you "
        "can mix several at once. Supported dimensions: free-text 'search' (matches "
        "name / preferred name / email / NDIS number), gender, min_age, max_age, "
        "diagnosis (primary + secondary + medical history), mobility (e.g. "
        "'wheelchair', 'walking stick'), medication, language, location. "
        "Examples: 'clients under 25 who need a wheelchair' → max_age=25, "
        "mobility=wheelchair; 'clients with a peanut allergy on metformin' → "
        "search=peanut, medication=metformin; 'Arabic-speaking clients in Sydney "
        "aged 60+' → language=arabic, location=Sydney, min_age=60. The backend "
        "enforces access control. Use filter_clients_by_criteria only when you must "
        "match on profile content this endpoint does not cover."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": (
                    "Free-text search across firstName, lastName, preferredName, "
                    "email and NDIS number. Also the right place for allergy or "
                    "other keyword terms (e.g. 'peanut')."
                ),
            },
            "gender": {
                "type": "string",
                "description": "Filter by gender (partial match, case-insensitive).",
            },
            "min_age": {
                "type": "integer",
                "description": "Minimum age in years (derived from dateOfBirth, inclusive).",
                "minimum": 0,
            },
            "max_age": {
                "type": "integer",
                "description": "Maximum age in years (derived from dateOfBirth, inclusive).",
                "minimum": 0,
            },
            "diagnosis": {
                "type": "string",
                "description": (
                    "Searches primaryDiagnosis, secondaryDiagnoses and medical "
                    "history titles/descriptions. e.g. 'autism', 'diabetes'."
                ),
            },
            "mobility": {
                "type": "string",
                "description": "Mobility need/aid. e.g. 'wheelchair', 'walking stick', 'walker'.",
            },
            "medication": {
                "type": "string",
                "description": "Current medication. e.g. 'metformin', 'insulin'.",
            },
            "language": {
                "type": "string",
                "description": "Spoken language. e.g. 'arabic', 'mandarin'.",
            },
            "location": {
                "type": "string",
                "description": "Address/location text — suburb, city or state. e.g. 'Sydney', 'VIC'.",
            },
            "page": {
                "type": "integer",
                "description": "Optional page number for pagination.",
                "minimum": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Optional records per page.",
                "minimum": 1,
                "maximum": 100,
            },
        },
    },
    run=_run,
)
