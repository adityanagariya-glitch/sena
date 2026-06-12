"""cannot_help — graceful refusal when no tool applies (off-topic or out of scope)."""
from tools.base import ToolSpec, ToolResult


def _run(inputs: dict | None) -> ToolResult:
    reason = (inputs or {}).get("reason", "").strip()
    return ToolResult(
        data={"reason": reason or "Out of scope"},
        next_hint=(
            "Tell the user politely that this isn't something you can help with. "
            "Steer them back to NDIS work topics (shifts, clients, staff, policies). "
            "Don't mention 'tools' or any internal mechanics."
        ),
    )


TOOL = ToolSpec(
    name="cannot_help",
    description=(
        "Use for ANY question whose answer doesn't live in a SENA tool (shifts, clients, "
        "staff, organisations) AND isn't a personal-memory fact about this "
        "user (name, preferences, timezone). This includes — but isn't limited to — "
        "general maths, arithmetic, code/database/MongoDB help, debugging, recipes, "
        "weather, world news, jokes, trivia, definitions of generic terms, opinions, or "
        "software questions. Looking easy to answer (e.g. '2+2') does NOT make it "
        "on-topic — refuse via this tool. Do NOT use for content-gate violations "
        "(blocked upstream) or for actions SENA simply doesn't expose yet (say so "
        "directly instead)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Brief internal reason — guides your user-facing reply.",
            }
        },
    },
    run=_run,
)
