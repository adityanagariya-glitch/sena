# rewriter.py
import boto3
import logging
from langfuse import observe, get_client

langfuse = get_client()

from config import REGION, REWRITER_MODEL

logger = logging.getLogger(__name__)

bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)

REWRITER_PROMPT = """You are a search query optimiser for an NDIS (National Disability Insurance Scheme) policy knowledge base.

Your job is to rewrite a user's conversational question into a precise search query that will retrieve the most relevant policy documents.

Rules:
- Use NDIS policy terminology and keywords
- Keep it concise - 10 words maximum
- Focus on the core policy topic being asked about
- Remove conversational filler ("can I", "what happens if", "I want to know")
- Use nouns and key terms, not full sentences
- If the question references a previous conversation, expand the reference into explicit terms
- If a reference cannot be resolved from context, preserve the original meaning instead of guessing
- Examples are only style guides. Never copy terms from examples unless they directly match the user's question or conversation context

Examples:
Question: what happens if someone gets hurt?
Rewritten search query: participant injury incident reporting

Question: can I share my patient's details with their family?
Rewritten search query: privacy consent information sharing family

Question: how long do I have to report it?
Recent conversation context: User asked about participant injury incident reporting.
Rewritten search query: participant injury incident reporting timeframe

Return ONLY the rewritten query, nothing else. No explanation, no punctuation at the end."""


def _is_valid_rewrite(rewritten: str) -> bool:
    if not rewritten or not rewritten.strip():
        return False

    text = rewritten.strip()
    lower = text.lower()

    invalid_prefixes = (
        "the rewritten query",
        "rewritten search query",
        "query:",
        "keywords:",
        "user is asking",
        "the user is asking",
        "this question",
    )
    if lower.startswith(invalid_prefixes):
        return False
    if "\n" in text or "\r" in text:
        return False
    if len(text.split()) > 10:
        return False
    if text.endswith((".", "!", "?")):
        return False
    return True

@observe(as_type="generation", name="rewrite-query", capture_input=False, capture_output=False)
def rewrite_query(question: str, recent_turns: str = "") -> tuple:
    """
    Rewrites user question into optimised KB search query using Nova Lite.
    Returns (rewritten_query, usage_dict). Falls back to original question on error.
    """
    if not question or not question.strip():
        return question, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    # Include recent turns context for follow-up questions
    context_section = ""
    if recent_turns:
        context_section = f"Recent conversation context:\n{recent_turns}\n\n"

    try:
        response = bedrock_runtime.converse(
            modelId=REWRITER_MODEL,
            system=[
                {
                    "type": "text",
                    "text": REWRITER_PROMPT,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            messages=[{"role": "user", "content": [{"text": f"{context_section}User question: {question}\n\nRewritten search query:"}]}],
            inferenceConfig={
                "maxTokens": 30,
                "temperature": 0.0
            }
        )
        rewritten  = response["output"]["message"]["content"][0]["text"].strip()
        raw_usage  = response.get("usage", {})
        input_total = raw_usage.get("inputTokens", 0) + raw_usage.get("cacheReadInputTokens", 0) + raw_usage.get("cacheWriteInputTokens", 0)
        output_total = raw_usage.get("outputTokens", 0)
        usage_dict = {
            "input_tokens":  input_total,
            "output_tokens": output_total,
            "total_tokens":  input_total + output_total,
        }
        final_query = question if not _is_valid_rewrite(rewritten) else rewritten
        if final_query == question:
            logger.warning(f"Invalid rewrite produced, using original query: '{rewritten}'")
        else:
            logger.info(f"Query rewritten: '{question[:60]}' -> '{rewritten}'")
        langfuse.update_current_generation(
            model=REWRITER_MODEL,
            input={"question": question, "recent_turns": recent_turns[:300] if recent_turns else None},
            output=final_query,
            usage_details={"input": usage_dict["input_tokens"], "output": usage_dict["output_tokens"]},
        )
        return final_query, usage_dict
    except Exception as e:
        logger.warning(f"Query rewriter error: {e} - using original query")
        return question, {"input_tokens": 0, "output_tokens": 0}

if __name__ == "__main__":
    test_questions = [
        "How much notice should staff give if unable to attend a shift?",
        "what happens if someone gets hurt?",
        "can I share my patient's details with their family?",
        "tell me more about that",
        "how long do I have to report it?",
        "what is the safeguarding policy?",
        "what do I do if a client misses their session?",
        "what is the incident reporting procedure for an injury to a participant?",
        "what is the participant privacy information sharing consent family policy?",
        "how long do I have to report it?"
    ]

    for q in test_questions:
        rewritten, _ = rewrite_query(q)
        print(f"Original:  {q}")
        print(f"Rewritten: {rewritten}")
        print()
