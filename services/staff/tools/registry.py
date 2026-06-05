"""Central tool registry — assembled from each tool's module.

Each tool module exports a TOOL constant (a ToolSpec). The registry stitches
them into a single dict keyed by name, plus a Bedrock-ready list.

When you add a new tool: import it here and add to ALL_TOOLS.
"""
from tools.base import ToolSpec

# ---- Profile / identity tools ----
from tools.profile.my_profile import TOOL as _T_MY_PROFILE
from tools.profile.get_user_type import TOOL as _T_GET_USER_TYPE
from tools.profile.set_my_timezone import TOOL as _T_SET_MY_TIMEZONE
from tools.profile.remember_about_me import TOOL as _T_REMEMBER_ABOUT_ME

# ---- Staff section tools ----
from tools.staff.list_my_shifts import TOOL as _T_LIST_MY_SHIFTS
from tools.staff.list_shifts_for_person import TOOL as _T_LIST_SHIFTS_FOR_PERSON
from tools.staff.list_org_shifts import TOOL as _T_LIST_ORG_SHIFTS
from tools.staff.get_shift_details import TOOL as _T_GET_SHIFT_DETAILS
from tools.staff.list_org_staff import TOOL as _T_LIST_ORG_STAFF

# ---- Client section tools ----
from tools.clients.list_my_clients import TOOL as _T_LIST_MY_CLIENTS
from tools.clients.list_org_clients import TOOL as _T_LIST_ORG_CLIENTS
from tools.clients.get_client_details import TOOL as _T_GET_CLIENT_DETAILS
from tools.clients.get_client_support_workers import TOOL as _T_GET_CLIENT_SW
from tools.clients.get_client_guardians import TOOL as _T_GET_CLIENT_GUARDIANS
from tools.clients.filter_clients_by_criteria import TOOL as _T_FILTER_CLIENTS
from tools.clients.search_clients import TOOL as _T_SEARCH_CLIENTS

# ---- Cross-section / shared ----
from tools.shared.find_person import TOOL as _T_FIND_PERSON
from tools.shared.list_my_organizations import TOOL as _T_LIST_MY_ORGS

# ---- Memory / Meta ----
from tools.memory.recall_conversation import TOOL as _T_RECALL_CONVERSATION
from tools.meta.clarify_with_user import TOOL as _T_CLARIFY
from tools.meta.cannot_help import TOOL as _T_CANNOT_HELP
from tools.meta.get_current_time import TOOL as _T_GET_CURRENT_TIME


# ── Tool groups (per section) ────────────────────────────────────────────────────
# The staff and client sections are INDEPENDENT: a user in one section can never
# reach the other's data. That boundary is the tool sets below — each section is
# given COMMON + its own tools, and ONLY its own.

# COMMON — identity/utility tools, neither staff- nor client-specific. Safe in every
# section (who am I, current time, my organisations, recall, clarify, cannot-help).
COMMON_TOOLS: list[ToolSpec] = [
    _T_MY_PROFILE,
    _T_GET_USER_TYPE,
    _T_SET_MY_TIMEZONE,
    _T_REMEMBER_ABOUT_ME,
    _T_LIST_MY_ORGS,
    _T_RECALL_CONVERSATION,
    _T_CLARIFY,
    _T_CANNOT_HELP,
    _T_GET_CURRENT_TIME,
]

# STAFF section ("Check Shifts" chip) — the worker's own work: shifts, rosters,
# shift details, and the staff/team directory. NO client data.
STAFF_TOOLS: list[ToolSpec] = [
    _T_LIST_MY_SHIFTS,
    _T_LIST_SHIFTS_FOR_PERSON,
    _T_LIST_ORG_SHIFTS,
    _T_GET_SHIFT_DETAILS,
    _T_LIST_ORG_STAFF,
    _T_FIND_PERSON,   # pinned to staff at dispatch — see tools/dispatcher.py
]

# CLIENT section ("Client's information" chip) — participant data: client list,
# details, medical/support workers, guardians, search/filter. NO shift/staff data.
CLIENT_TOOLS: list[ToolSpec] = [
    _T_LIST_MY_CLIENTS,
    _T_LIST_ORG_CLIENTS,
    _T_GET_CLIENT_DETAILS,
    _T_GET_CLIENT_SW,
    _T_GET_CLIENT_GUARDIANS,
    _T_FILTER_CLIENTS,
    _T_SEARCH_CLIENTS,
    _T_FIND_PERSON,   # pinned to client at dispatch — see tools/dispatcher.py
]

# Per-section allow-lists the agent may use.
TOOLS_BY_SCOPE: dict[str, list[ToolSpec]] = {
    "staff":  COMMON_TOOLS + STAFF_TOOLS,
    "client": COMMON_TOOLS + CLIENT_TOOLS,
}
VALID_SCOPES: tuple[str, ...] = tuple(TOOLS_BY_SCOPE.keys())

# Full set, deduped by name (find_person appears in two groups) — used only by the
# dispatcher's name→tool lookup. Scope enforcement is done via the allow-list
# passed to run_tool, never by exposing this full set to a Bedrock call.
ALL_TOOLS: list[ToolSpec] = list(
    {t.name: t for t in (COMMON_TOOLS + STAFF_TOOLS + CLIENT_TOOLS)}.values()
)
TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in ALL_TOOLS}


def tools_for_scope(scope: str) -> list[ToolSpec]:
    """Return the ToolSpecs available in a section ('staff' or 'client')."""
    try:
        return TOOLS_BY_SCOPE[scope]
    except KeyError:
        raise ValueError(
            f"Unknown scope {scope!r}; expected one of {', '.join(VALID_SCOPES)}"
        )


def tool_names_for_scope(scope: str) -> set[str]:
    """Return the set of tool names allowed in a section (for enforcement)."""
    return {t.name for t in tools_for_scope(scope)}


def bedrock_tool_config(scope: str) -> dict:
    """Build the Bedrock Converse `toolConfig` for ONE section only.

    `scope` is required: staff and client are independent, so each Bedrock call is
    handed only that section's tools — the model literally cannot pick the other
    section's tools because they aren't offered.
    """
    return {"tools": [t.to_bedrock_spec() for t in tools_for_scope(scope)]}
