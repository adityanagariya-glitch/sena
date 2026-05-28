"""remember_about_me — save an arbitrary fact/preference about the user.

Called whenever the user volunteers something they want remembered:
  • "my name is Jake" / "call me Jake" / "remember my name is Jake"
  • "I prefer 24-hour time"
  • "I like tables, not bullet points"
  • "remember I work weekends only"

Writes to AgentCore (24h session + auto-extraction into long-term preferences)
AND DynamoDB chat_audit (90-day TTL). Both layers are non-fatal — if one fails,
the other still records.

The tz `set_my_timezone` tool stays separate because it has its own resolver
and explicit 30-day re-ask behaviour.
"""
import sys

from config import VERBOSE
from tools.base import ToolSpec, ToolResult


_VALID_KINDS = ("name", "format_pref", "general")


def _run(inputs: dict | None) -> ToolResult:
    inputs = inputs or {}
    fact = (inputs.get("fact") or "").strip()
    kind = (inputs.get("kind") or "general").strip().lower()
    if kind not in _VALID_KINDS:
        kind = "general"

    if not fact:
        return ToolResult(error="Missing required input: fact (one short sentence about the user).")

    if VERBOSE:
        print(f"[remember_about_me] kind={kind} fact={fact!r}", file=sys.stderr)

    from memory import _save_about_user
    saved = _save_about_user(fact, kind=kind)

    if not saved:
        return ToolResult(
            data={"saved": False, "fact": fact, "kind": kind},
            next_hint=(
                "Memory layer wasn't reachable just now. Tell the user briefly "
                "that you'll keep it in mind for this chat, but it may not "
                "persist for next time. Don't dwell on the failure."
            ),
        )

    # Best-effort: also update in-process user_context for name + format_pref
    # so the agent uses them immediately in this session without waiting for
    # AgentCore extraction to surface them.
    from state import user_context
    if kind == "name":
        # Extract the bare name if the fact looks like "Their name is Jake."
        # We don't try to be too clever — store the whole fact as a hint.
        user_context["name_hint"] = fact

    return ToolResult(
        data={"saved": True, "fact": fact, "kind": kind},
        next_hint=(
            "Confirm to the user in one short Aussie-flavoured line that you've "
            "remembered it (e.g. 'Cheers Jake, got that on file' / 'Noted — "
            "I'll keep that in mind'). Use their name if you know it. NEVER "
            "mention how long it's stored for. Then continue with whatever "
            "they were asking next, or just end on the confirmation."
        ),
    )


TOOL = ToolSpec(
    name="remember_about_me",
    description=(
        "Save a fact or preference about the user so the assistant can use it "
        "now and in future sessions. Call this whenever the user volunteers "
        "something personal they want remembered — examples: 'my name is "
        "Jake', 'call me Jake', 'remember my name', 'I prefer 24-hour time', "
        "'I like data in tables', 'remember I work weekends only'. After "
        "calling, briefly confirm to the user in one line."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": (
                    "The fact to remember, rewritten as a complete sentence "
                    "ABOUT THE USER. Examples: 'Their name is Jake.' / "
                    "'They prefer 24-hour time format.' / 'They like data "
                    "presented as tables, not bullets.' / 'They work "
                    "weekends only.' Keep it short and factual."
                ),
            },
            "kind": {
                "type": "string",
                "enum": list(_VALID_KINDS),
                "description": (
                    "Short slug categorising the fact. 'name' for the user's "
                    "name, 'format_pref' for output format preferences, "
                    "'general' for anything else."
                ),
            },
        },
        "required": ["fact"],
    },
    run=_run,
)
