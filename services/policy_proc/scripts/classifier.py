# classifier.py
import boto3
import json
import logging
import re

<<<<<<< HEAD:services/policy_proc/scripts/classifier.py
from services.policy_proc.scripts.config import REGION, CLASSIFIER_MODEL, MESSAGES
=======
from config import REGION, CLASSIFIER_MODEL, MESSAGES
>>>>>>> 0632581 (changes in policy-proc):scripts/classifier.py

logger = logging.getLogger(__name__)

bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)

CLASSIFIER_PROMPT = """You are an intent classifier for an NDIS (National Disability Insurance Scheme) policy chatbot.

Classify the user's question into exactly one of these categories:

NDIS
<<<<<<< HEAD:services/policy_proc/scripts/classifier.py
   Any question that could reasonably be answered by an NDIS policy document, 
   a disability support organisation's internal policies, or workplace procedures 
   related to disability support work. This includes questions about participant care, 
   incident reporting, privacy, complaints, safeguarding, worker obligations, 
   workforce management, HR policies, leave entitlements, salary, staff conduct, 
   workplace procedures, or anything a support worker or coordinator might need 
   to know in their role.

SENSITIVE
  The message itself contains real personal details: full names, phone numbers, physical
  addresses, participant IDs, email addresses, or other identifying information about a
  real individual. Policy questions that reference PII conceptually (e.g. "can I share a
  participant's name with their family?") are NOT sensitive — classify those as NDIS.

OFF_TOPIC
  Questions completely unrelated to disability support work, NDIS, or any aspect of working 
  in a disability support organisation. Examples: general knowledge, science, weather, sports, 
  cooking, technology, unrelated to work, entertainment. 

HARMFUL
  Questions with malicious, dangerous, or abusive intent — e.g. asking how to harm,
  exploit, or deceive a participant or colleague. Note: questions about reporting abuse,
  neglect, or safeguarding incidents are NDIS, not HARMFUL.

Examples of NDIS (pass through to KB):
- "What is the safeguarding policy?" → NDIS
- "How do I report an incident?" → NDIS
- "Can I share patient details with family?" → NDIS
- "What is the salary for a support worker at this organisation?" → NDIS (workforce policy)
- "How do I apply for parental leave?" → NDIS (organisation HR procedure)
- "What are my entitlements as a support worker?" → NDIS (workforce policy)
- "What is the WHS policy?" → NDIS (workplace policy)
- "I made a mistake with a client, what do I do?" → NDIS (incident reporting)
- "Can you list all the policies?" → NDIS

Examples of OFF_TOPIC (block):
- "What is the weather today?" → OFF_TOPIC
- "Who won the football?" → OFF_TOPIC
- "What is AWS?" → OFF_TOPIC
- "How do I cook pasta?" → OFF_TOPIC

Examples of SENSITIVE (block):
- "My participant John Smith at 42 Main St needs help" → SENSITIVE
- "Can I share participant information with family?" → NDIS (policy question, NOT sensitive)
=======
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
>>>>>>> 0632581 (changes in policy-proc):scripts/classifier.py

Respond with a JSON object in this exact format — no preamble, no markdown fences:
{
  "label": "NDIS",
  "confidence": 0.95,
  "reason": "User is asking about incident reporting procedure."
}"""

<<<<<<< HEAD:services/policy_proc/scripts/classifier.py
MESSAGES = {
    "OFF_TOPIC": "I can only help with NDIS and organisation policy questions.",
    "HARMFUL":   "I'm not able to help with that.",
    "SENSITIVE": (
        "It looks like your message contains personal details. "
        "Please rephrase your question without names, addresses, or ID numbers "
        "and I'll do my best to help."
    ),
    "FALLBACK":  "I'm not sure how to help with that. Try rephrasing your question.",
}


def classify(question: str) -> dict:
    """
    Classifies user question intent using Nova Micro.
    Returns dict with label, confidence, reason.
    """
    if not question or not question.strip():
        logger.warning("Empty question received")
        return {"label": "NDIS", "confidence": 0.5, "reason": "Empty question — defaulting to NDIS"}
=======
def classify(question: str, recent_turns: str = "") -> dict:
    """
    Classifies user question into NDIS, GREETING, SENSITIVE, OFF_TOPIC, or HARMFUL.
    Accepts recent_turns for context-aware classification of follow-up questions.
    """
    if not question or not question.strip():
        return {"label": "NDIS", "confidence": 0.5, "reason": "Empty question"}

    context_section = ""
    if recent_turns:
        context_section = f"\nRecent conversation context (use this to understand follow-up questions):\n{recent_turns}\n"

    prompt = f"""{CLASSIFIER_PROMPT}
{context_section}
User message: {question}

Classification:"""
>>>>>>> 0632581 (changes in policy-proc):scripts/classifier.py

    try:
        response = bedrock_runtime.converse(
            modelId=CLASSIFIER_MODEL,
<<<<<<< HEAD:services/policy_proc/scripts/classifier.py
            messages=[{
                "role": "user",
                "content": [{"text": f"{CLASSIFIER_PROMPT}\n\nQuestion: {question}"}]
            }]
        )

        raw = response["output"]["message"]["content"][0]["text"].strip()
        logger.debug(f"Classifier raw response: {raw}")

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                logger.warning("Could not parse classifier response — defaulting to NDIS")
                result = {"label": "NDIS", "confidence": 0.5, "reason": "Parse error — defaulting to NDIS"}

        logger.info(f"Classified: {result['label']} ({result['confidence']}) — {result['reason']}")
        return result

    except Exception as e:
        logger.error(f"Classifier error: {e}")
        return {"label": "NDIS", "confidence": 0.5, "reason": f"Classifier error — defaulting to NDIS"}


def should_block(classification: dict) -> tuple[bool, str | None]:
    """
    Returns (True, message) if question should be blocked.
    Returns (False, None) if question should proceed to retrieval.
    """
    label = classification.get("label", "NDIS")
    if label in MESSAGES and label != "NOT_IN_KB" and label != "ERROR":
        if label in ("OFF_TOPIC", "HARMFUL", "SENSITIVE"):
            return True, MESSAGES[label]
    return False, None
=======
            messages=[{"role": "user", "content": [{"text": prompt}]}]
        )
        raw  = response["output"]["message"]["content"][0]["text"].strip()
        data = json.loads(raw)
        label      = data.get("label", "NDIS").upper()
        confidence = float(data.get("confidence", 0.5))
        reason     = data.get("reason", "")
        logger.info(f"Classified: {label} ({confidence}) — {reason}")
        return {"label": label, "confidence": confidence, "reason": reason}

    except Exception as e:
        logger.warning(f"Classifier error: {e} — defaulting to NDIS")
        return {"label": "NDIS", "confidence": 0.5, "reason": "Classifier error"}


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
>>>>>>> 0632581 (changes in policy-proc):scripts/classifier.py


if __name__ == "__main__":
    while True:
        q = input("\nEnter question (or 'quit'): ").strip()
        if q.lower() == "quit":
            break
        result = classify(q)
        blocked, message = should_block(result)
        print(f"   Label: {result['label']} | Confidence: {result['confidence']}")
        print(f"   Blocked: {blocked}" + (f" | Message: {message}" if blocked else ""))