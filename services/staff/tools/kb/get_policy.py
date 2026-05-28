"""get_policy — RAG lookup across all configured Bedrock Knowledge Bases.

Uses kb_query.query_kbs which retrieves from every configured KB in parallel
(via `bedrock_agent_runtime.retrieve`), merges top-K chunks by score, and runs
a single Sonnet generate call. Latency ≈ same as a single-KB call.
"""
import sys

from config import (
    VERBOSE,
    BEDROCK_KB_IDS,
)
from style_guide import AUSTRALIAN_ENGLISH
from tools.base import ToolSpec, ToolResult
from kb_query import query_kbs


def _run(inputs: dict | None) -> ToolResult:
    topic = (inputs or {}).get("topic", "").strip()
    if not topic:
        return ToolResult(error="Missing required input: topic.")

    if not BEDROCK_KB_IDS:
        return ToolResult(
            error="Knowledge base is not configured.",
            next_hint=(
                "No KB available — tell the user politely and recommend they check "
                "with their coordinator/team leader for the policy."
            ),
        )

    if VERBOSE:
        print(f"[get_policy] topic={topic!r} kbs={len(BEDROCK_KB_IDS)}", file=sys.stderr)

    system_prompt = (
        f"{AUSTRALIAN_ENGLISH} You are providing NDIS policy/procedure context "
        "to be relayed by the SENA assistant.\n\n"
        "Extract ONLY the relevant policy, procedure, or compliance facts from "
        "the reference material that will be provided below. Be concise and "
        "direct — no preamble, no 'I reckon you're after', no restating the "
        "question. If the reference material doesn't cover the question, return "
        'exactly: "I don\'t have enough confirmed information to answer that."\n\n'
        "Australian English (organisation, recognise, behaviour). Dates DD/MM/YYYY. "
        "No \"mate\" in compliance contexts.\n\n"
        "SOURCE PRIVACY: never mention documents, search results, knowledge bases, "
        "retrieval, citations, sources, or any internal mechanics."
    )

    try:
        answer, _chunks = query_kbs(topic, system_prompt, kb_ids=BEDROCK_KB_IDS)
    except Exception as e:
        if VERBOSE:
            print(f"[get_policy] multi-KB query failed: {type(e).__name__}: {e}", file=sys.stderr)
        return ToolResult(
            error=f"KB lookup failed: {type(e).__name__}",
            next_hint="Apologise briefly, suggest checking with the team leader.",
        )

    answer = (answer or "").strip()

    if not answer or "I don't have enough confirmed information" in answer:
        return ToolResult(
            data={"topic": topic, "answer": None},
            next_hint=(
                "KB has no documented answer for this topic. Tell the user the policy "
                "isn't on file yet and suggest they check with their coordinator."
            ),
        )

    return ToolResult(data={"topic": topic, "answer": answer})


TOOL = ToolSpec(
    name="get_policy",
    description=(
        "Look up a SENA / NDIS policy, procedure, requirement, standard, code-of-conduct "
        "item, or compliance guideline from the documented knowledge base(s). Searches "
        "ALL configured KBs in parallel and merges the best context. Use for: 'shift "
        "policy', 'sleepover policy', 'what's the policy on X', 'what's the go with X', "
        "'do i need to sign anything', 'compliance requirements', 'NDIS practice "
        "standards', 'medication management policy', 'how should I handle X'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": (
                    "The policy topic or question, rewritten as a clear standalone "
                    "search query (e.g. 'sleepover shift pay rules' rather than 'what's "
                    "the go with sleepovers'). Be specific so the KB retrieval picks the "
                    "right chunks."
                ),
            },
        },
        "required": ["topic"],
    },
    run=_run,
)
