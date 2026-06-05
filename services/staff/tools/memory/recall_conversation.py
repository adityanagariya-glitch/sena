"""recall_conversation — answer from session transcript + prior-session summaries."""
import sys

from config import VERBOSE
from tools.base import ToolSpec, ToolResult


def _run(inputs: dict | None) -> ToolResult:
    question = (inputs or {}).get("question", "").strip()
    if not question:
        return ToolResult(error="Missing required input: question.")

    if VERBOSE:
        print(f"[recall_conversation] question={question!r}", file=sys.stderr)

    try:
        from memory import _try_answer_from_memory
        answer = _try_answer_from_memory(question)
        if answer:
            return ToolResult(data={"answer": answer})
        return ToolResult(
            data={"answer": None},
            next_hint=(
                "Nothing relevant in conversation memory — tell the user politely "
                "and offer to fetch fresh data instead."
            ),
        )
    except Exception as e:
        return ToolResult(
            error=f"Memory recall failed: {type(e).__name__}",
            next_hint="Apologise briefly, offer to fetch fresh data.",
        )


TOOL = ToolSpec(
    name="recall_conversation",
    description=(
        "Answer from the conversation transcript (this session) or summaries of prior "
        "sessions — NOT from live data. Use ONLY when the user explicitly references "
        "memory: 'what did you tell me earlier', 'you said', 'remind me', 'last time we "
        "talked', 'what did i ask before', 'in our previous chat'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The user's memory-recall question, verbatim.",
            }
        },
        "required": ["question"],
    },
    run=_run,
)
