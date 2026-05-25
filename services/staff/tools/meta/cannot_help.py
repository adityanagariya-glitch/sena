"""cannot_help — graceful refusal when no tool applies (off-topic or out of scope)."""
from tools.base import ToolSpec, ToolResult


def _run(inputs):
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
        "Use when the user's request is genuinely out of scope (off-topic, asking about "
        "things SENA doesn't cover, or requesting actions you can't perform like editing "
        "data). Do NOT use for content-gate violations (those are blocked upstream) — "
        "only for legitimate but unsupportable requests."
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
