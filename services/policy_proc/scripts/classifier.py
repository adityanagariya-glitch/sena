# classifier.py
import boto3
import json
import logging
import re
from langfuse import observe, get_client

langfuse = get_client()

from config import REGION, CLASSIFIER_MODEL, MESSAGES

logger = logging.getLogger(__name__)

bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)

CLASSIFIER_PROMPT = """You are an intent classifier for an NDIS (National Disability Insurance Scheme) policy chatbot.

Classify the user's question into exactly one of these categories:

NDIS
   Any question that could reasonably be answered by an NDIS policy document,
   a disability support organisation's internal policies, or workplace procedures
   related to disability support work. This includes questions about participant care,
   incident reporting, privacy, complaints, safeguarding, worker obligations,
   workforce management, HR policies, leave entitlements, salary, staff conduct,
   workplace procedures, or anything a support worker or coordinator might need
   to know in their role.
   
   IMPORTANT — also classify as NDIS:
   - Vague or incomplete questions that could relate to policy (e.g. "tell me more", 
     "what about leave?", "and incidents?", "what does that mean?")
   - Single word or short queries that could be policy topics (e.g. "safeguarding", 
     "incidents", "leave", "complaints")
   - Questions with spelling mistakes or poor grammar that seem policy-related
   - Follow-up questions referencing a previous answer (e.g. "tell me more about that",
     "what happens next?", "and if I don't?")
   - Anything even loosely related to disability support work — when in doubt, classify NDIS

GREETING
   Friendly conversational messages with no policy question — greetings, farewells,
   expressions of thanks, small talk. These should get a warm response, not a block.
   Examples: "hi", "hello", "good morning", "good afternoon", "good day", "hey",
   "thanks", "thank you", "bye", "see you", "how are you", "great thanks",
   "that helped", "cheers", "no worries"

SENSITIVE
   The message itself contains real personal details: full names combined with other
   identifiers (phone numbers, physical addresses, participant IDs, email addresses).
   Policy questions that reference PII conceptually are NOT sensitive — classify as NDIS.
   Example: "My participant John Smith at 42 Main St needs help" → SENSITIVE
   Example: "Can I share a participant's name with their family?" → NDIS

OFF_TOPIC
   Questions completely unrelated to disability support work, NDIS, or working in a
   disability support organisation AND clearly not a greeting.
   Only classify as OFF_TOPIC when you are certain the question has no possible
   connection to disability support work.
   Examples: weather, sports scores, cooking recipes, entertainment, general science.
   When in doubt — classify as NDIS, not OFF_TOPIC.

HARMFUL
   Questions with clear malicious, dangerous, or abusive intent — asking how to harm,
   exploit, or deceive a participant or colleague.
   Note: questions about reporting abuse or safeguarding incidents are NDIS, not HARMFUL.

Examples:
- "hi" → GREETING
- "hello there" → GREETING  
- "good morning" → GREETING
- "thanks for that" → GREETING
- "tell me more" → NDIS (follow-up — assume policy context)
- "what about leave?" → NDIS (vague but policy-related)
- "safeguarding" → NDIS (single word policy topic)
- "inclidents" → NDIS (misspelled but policy-related)
- "what is the safeguarding policy?" → NDIS
- "how do I report an incident?" → NDIS
- "can I share patient details with family?" → NDIS
- "what are my entitlements?" → NDIS
- "I made a mistake with a client, what do I do?" → NDIS
- "tell me something" → GREETING (no policy context)
- "what is the weather today?" → OFF_TOPIC
- "who won the football?" → OFF_TOPIC
- "how do I cook pasta?" → OFF_TOPIC
- "how do I hurt someone?" → HARMFUL
- "My participant John Smith at 42 Main St needs help" → SENSITIVE

Respond with a JSON object in this exact format — no preamble, no markdown fences:
{
  "label": "NDIS",
  "confidence": 0.95,
  "reason": "User is asking about incident reporting procedure."
}"""

@observe(as_type="generation", name="classify", capture_input=False, capture_output=False)
def classify(question: str, recent_turns: str = "") -> dict:
    """
    Classifies user question into NDIS, GREETING, SENSITIVE, OFF_TOPIC, or HARMFUL.
    Accepts recent_turns for context-aware classification of follow-up questions.
    """
    if not question or not question.strip():
        return {"label": "NDIS", "confidence": 0.5, "reason": "Empty question"}

    context_section = ""
    if recent_turns:
        context_section = f"Recent conversation context (use this to understand follow-up questions):\n{recent_turns}\n\n"

    try:
        response = bedrock_runtime.converse(
            modelId=CLASSIFIER_MODEL,
            system=[
                {"text": CLASSIFIER_PROMPT},
                {"cachePoint": {"type": "default"}},
            ],
            messages=[{"role": "user", "content": [{"text": f"{context_section}User message: {question}\n\nClassification:"}]}]
        )
        raw  = response["output"]["message"]["content"][0]["text"].strip()
        data = json.loads(raw)
        label      = data.get("label", "NDIS").upper()
        confidence = float(data.get("confidence", 0.5))
        reason     = data.get("reason", "")
        raw_usage  = response.get("usage", {})
        input_total = raw_usage.get("inputTokens", 0) + raw_usage.get("cacheReadInputTokens", 0) + raw_usage.get("cacheWriteInputTokens", 0)
        output_total = raw_usage.get("outputTokens", 0)
        langfuse.update_current_generation(
            model=CLASSIFIER_MODEL,
            input=question,
            output={"label": label, "confidence": confidence, "reason": reason},
            usage_details={"input": input_total, "output": output_total, "total": input_total + output_total},
            metadata={"service": "policy_proc_classifier"},
        )
        logger.info(f"Classified: {label} ({confidence}) — {reason}")
        return {
            "label":      label,
            "confidence": confidence,
            "reason":     reason,
            "usage": {
                "input_tokens":  input_total,
                "output_tokens": output_total,
                "total_tokens":  input_total + output_total,
            },
        }

    except Exception as e:
        logger.warning(f"Classifier error: {e} — defaulting to NDIS")
        return {"label": "NDIS", "confidence": 0.5, "reason": "Classifier error", "usage": {"input_tokens": 0, "output_tokens": 0}}


def should_block(classification: dict) -> tuple[bool, str]:
    label = classification.get("label", "NDIS")

    if label == "OFF_TOPIC":
        return True, MESSAGES["OFF_TOPIC"]
    if label == "HARMFUL":
        return True, MESSAGES["HARMFUL"]
    if label == "SENSITIVE":
        return True, MESSAGES["SENSITIVE"]

    # GREETING and NDIS both pass through — not blocked
    return False, ""


if __name__ == "__main__":
    while True:
        q = input("\nEnter question (or 'quit'): ").strip()
        if q.lower() == "quit":
            break
        result = classify(q)
        blocked, message = should_block(result)
        print(f"   Label: {result['label']} | Confidence: {result['confidence']}")
        print(f"   Blocked: {blocked}" + (f" | Message: {message}" if blocked else ""))