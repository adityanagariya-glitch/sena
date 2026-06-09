"""
Prompt construction for summary consolidation.

The prompt lives here — in code, under version control — because it is
application logic, not configuration. Secrets and deployment values belong
in .env; the prompt does not.
"""

# ── System prompt ─────────────────────────────────────────────────────────────
# Sent as the "system" turn to set Claude's role and hard constraints.

SYSTEM_PROMPT = """\
You are an expert summarizer. Your job is to read multiple summaries of \
different pieces of content and produce a single, coherent consolidated summary.

Rules you must follow:
- Preserve every key point that appears across the input summaries.
- Eliminate redundancy: if the same point appears in multiple summaries, \
state it once.
- Do not introduce information that is not present in the input summaries.
- Keep the output concise but complete — do not pad with filler phrases.
- Write in clear, professional prose. No bullet points unless the inputs \
themselves are structured that way.
- Output only the consolidated summary text. No preamble, no explanation, \
no meta-commentary.\
"""

# ── User prompt template ──────────────────────────────────────────────────────
# {count}     — integer: number of summaries provided
# {summaries} — formatted, numbered list of summary texts

_USER_TEMPLATE = """\
Below are {count} summaries. Consolidate them into a single summary.

{summaries}

Consolidated summary:\
"""


def _format_summaries(summaries: list[str]) -> str:
    """Return summaries as a numbered list, each clearly delimited."""
    lines = []
    for i, summary in enumerate(summaries, start=1):
        lines.append(f"[Summary {i}]\n{summary.strip()}")
    return "\n\n".join(lines)


def build_messages(summaries: list[str]) -> list[dict]:
    """
    Build the messages list for the Bedrock Claude Messages API.

    Returns a list with a single user turn. The system prompt is returned
    separately via `get_system_prompt()` and passed at the top level of the
    Bedrock request body.

    Example output:
        [
            {
                "role": "user",
                "content": "Below are 5 summaries. Consolidate them..."
            }
        ]
    """
    user_content = _USER_TEMPLATE.format(
        count=len(summaries),
        summaries=_format_summaries(summaries),
    )
    return [{"role": "user", "content": user_content}]


def get_system_prompt() -> str:
    """Return the system prompt string."""
    return SYSTEM_PROMPT