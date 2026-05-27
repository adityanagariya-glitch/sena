# rewriter.py
import boto3
import logging

from config import REGION

logger = logging.getLogger(__name__)

bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)

REWRITER_MODEL = "amazon.nova-lite-v1:0"

REWRITER_PROMPT = """You are a search query optimiser for an NDIS (National Disability Insurance Scheme) policy knowledge base.

Your job is to rewrite a user's conversational question into a precise search query that will retrieve the most relevant policy documents.

Rules:
- Use NDIS policy terminology and keywords
- Keep it concise — 10 words maximum
- Focus on the core policy topic being asked about
- Remove conversational filler ("can I", "what happens if", "I want to know")
- Use nouns and key terms, not full sentences
- If the question references a previous conversation, expand the reference into explicit terms

Return ONLY the rewritten query, nothing else. No explanation, no punctuation at the end."""


def rewrite_query(question: str, recent_turns: str = "") -> str:
    """
    Rewrites user question into optimised KB search query using Nova Lite.
    Falls back to original question on error.
    """
    if not question or not question.strip():
        return question

    # Include recent turns context for follow-up questions
    context_section = ""
    if recent_turns:
        context_section = f"\nRecent conversation context:\n{recent_turns}\n"

    prompt = f"""{REWRITER_PROMPT}
{context_section}
User question: {question}

Rewritten search query:"""

    try:
        response = bedrock_runtime.converse(
            modelId=REWRITER_MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}]
        )
        rewritten = response["output"]["message"]["content"][0]["text"].strip()
        logger.info(f"Query rewritten: '{question[:60]}' → '{rewritten}'")
        return rewritten

    except Exception as e:
        logger.warning(f"Query rewriter error: {e} — using original query")
        return question


if __name__ == "__main__":
    test_questions = [
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
        rewritten = rewrite_query(q)
        print(f"Original:  {q}")
        print(f"Rewritten: {rewritten}")
        print()