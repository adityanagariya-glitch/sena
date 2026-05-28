"""clarify_with_user — ask the user a follow-up question when input is ambiguous."""
from tools.base import ToolSpec, ToolResult


def _run(inputs: dict | None) -> ToolResult:
    question = (inputs or {}).get("question", "").strip()
    if not question:
        return ToolResult(error="Missing required input: question.")

    return ToolResult(
        data={"clarification": question},
        next_hint=(
            "Now write the user-facing message that asks this clarifying question. "
            "Be warm, brief, and offer the concrete options where relevant."
        ),
    )


TOOL = ToolSpec(
    name="clarify_with_user",
    description=(
        "Ask the user a clarifying question when the request is ambiguous (e.g. multiple "
        "people match a name, multiple possible interpretations, missing details). Use "
        "ONLY when truly ambiguous — don't use as a stalling tactic. Prefer making a best "
        "guess and acting when the answer is reasonably clear."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "The clarifying question to ask the user. Include the specific options "
                    "where helpful (e.g. 'Found 3 Sarahs: Sarah Smith (client), Sarah Lee "
                    "(client), Sarah Jones (staff). Which one?')."
                ),
            }
        },
        "required": ["question"],
    },
    run=_run,
)
