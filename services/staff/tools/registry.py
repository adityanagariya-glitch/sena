"""Central tool registry — assembled from each tool's module.

Each tool module exports a TOOL constant (a ToolSpec). The registry stitches
them into a single dict keyed by name, plus a Bedrock-ready list.

When you add a new tool: import it here and add to ALL_TOOLS.
"""
from tools.base import ToolSpec

# ---- Profile / identity tools ----
from tools.profile.my_profile import TOOL as _T_MY_PROFILE
from tools.profile.set_my_timezone import TOOL as _T_SET_MY_TIMEZONE

# ---- Staff section tools ----
from tools.staff.list_my_shifts import TOOL as _T_LIST_MY_SHIFTS
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

# ---- Cross-section / shared ----
from tools.shared.find_person import TOOL as _T_FIND_PERSON

# ---- KB / Memory / Meta ----
from tools.kb.get_policy import TOOL as _T_GET_POLICY
from tools.memory.recall_conversation import TOOL as _T_RECALL_CONVERSATION
from tools.meta.clarify_with_user import TOOL as _T_CLARIFY
from tools.meta.cannot_help import TOOL as _T_CANNOT_HELP


ALL_TOOLS: list[ToolSpec] = [
    _T_MY_PROFILE,
    _T_SET_MY_TIMEZONE,
    _T_LIST_MY_SHIFTS,
    _T_LIST_ORG_SHIFTS,
    _T_GET_SHIFT_DETAILS,
    _T_LIST_ORG_STAFF,
    _T_LIST_MY_CLIENTS,
    _T_LIST_ORG_CLIENTS,
    _T_GET_CLIENT_DETAILS,
    _T_GET_CLIENT_SW,
    _T_GET_CLIENT_GUARDIANS,
    _T_FILTER_CLIENTS,
    _T_FIND_PERSON,
    _T_GET_POLICY,
    _T_RECALL_CONVERSATION,
    _T_CLARIFY,
    _T_CANNOT_HELP,
]

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in ALL_TOOLS}


def bedrock_tool_config() -> dict:
    """Build the `toolConfig` block for the Bedrock Converse API."""
    return {
        "tools": [t.to_bedrock_spec() for t in ALL_TOOLS],
    }
