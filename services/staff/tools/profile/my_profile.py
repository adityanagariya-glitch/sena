"""my_profile — answer from user_context (no API call needed)."""
import sys

from config import VERBOSE
from state import user_context
from tools.base import ToolSpec, ToolResult


def _run(inputs):
    if VERBOSE:
        print("[my_profile] reading user_context", file=sys.stderr)

    return ToolResult(
        data={
            "email": user_context.get("email"),
            "user_type": user_context.get("user_type"),
            "staff_type": user_context.get("staff_type"),
            "roles": user_context.get("roles") or [],
            "organization_id": user_context.get("organization_id"),
            "user_id": user_context.get("user_id"),
            "authenticated": bool(user_context.get("authenticated")),
        }
    )


TOOL = ToolSpec(
    name="my_profile",
    description=(
        "Return the LOGGED-IN user's own profile (role, email, organisation, user type). "
        "Instant — no API call. Use for: 'what is my role', 'who am i', 'what's my email', "
        "'my user type', 'my organisation', 'am i an admin', 'do i have permission to X', "
        "'what type of user am I'."
    ),
    input_schema={"type": "object", "properties": {}},
    run=_run,
)
