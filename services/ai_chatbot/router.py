"""Bedrock Haiku classification: route queries to Staff or Policy service.

Uses Claude Haiku to classify queries and route them appropriately.
"""
import logging
import json
from typing import Dict, Any, Optional
import boto3

logger = logging.getLogger(__name__)

# Match the staff service: same region + active inference-profile model,
# called through the Converse API (the legacy claude-3-haiku invoke_model
# path is now access-denied on this account).
REGION = "ap-southeast-2"
MODEL_ID = "au.anthropic.claude-sonnet-4-6"

# Bedrock client
_bedrock_client = None


def get_bedrock_client():
    """Lazy-load Bedrock runtime client."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-runtime", region_name=REGION)
    return _bedrock_client


async def classify_query(
    question: str,
    model_id: str = MODEL_ID,
) -> Dict[str, Any]:
    """Classify query using Claude Haiku.

    Returns:
        {
            "service": "staff|policy|both",
            "confidence": 0.0-1.0,
            "reason": "explanation",
            "priority": "staff|policy",
        }
    """
    prompt = f"""You are a router. Classify the user's question into exactly one category:

- "staff": staff operations — shifts, rosters, payroll, allowances, leave requests, timesheets, "my" work details.
- "policy": organisational policy, compliance, rules, procedures, restrictions, what is/isn't allowed.
- "both": the question genuinely needs both staff data AND policy rules to answer.
- "none": the question is unrelated to staff operations or policy (e.g. greetings, weather, math, general chit-chat, anything out of scope).

Question: {question}

Respond with ONLY a JSON object, no prose:
{{
  "service": "staff" | "policy" | "both" | "none",
  "confidence": 0.0 to 1.0,
  "reason": "short explanation",
  "priority": "staff" | "policy"
}}
"""

    try:
        client = get_bedrock_client()
        resp = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 200, "temperature": 0},
        )
        # Converse returns {"output": {"message": {"content": [{"text": "..."}]}}}
        text = ""
        for block in resp["output"]["message"]["content"]:
            if "text" in block:
                text += block["text"]
        text = text.strip()

        try:
            # Be tolerant of markdown fences / surrounding prose
            start, end = text.find("{"), text.rfind("}")
            data = json.loads(text[start:end + 1] if start != -1 else text)
            service = data.get("service", "none")
            if service not in ("staff", "policy", "both", "none"):
                service = "none"
            return {
                "service": service,
                "confidence": float(data.get("confidence", 0.5)),
                "reason": data.get("reason", ""),
                "priority": data.get("priority", "staff"),
            }
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"Failed to parse Haiku response: {text!r}")
            return {
                "service": "none",
                "confidence": 0.0,
                "reason": "Could not parse classifier output.",
                "priority": "staff",
            }
    except Exception as e:
        logger.exception(f"Bedrock classification failed: {e}")
        return {
            "service": "none",
            "confidence": 0.0,
            "reason": f"Classifier error: {e}",
            "priority": "staff",
        }


async def route_query(
    question: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Route query to appropriate service(s).

    Args:
        question: User question
        context: Request context (user_id, org_id, role)

    Returns:
        {
            "target_services": ["staff", "policy"],
            "classification": {...},
            "routing_reason": "string"
        }
    """
    classification = await classify_query(question)

    service_target = classification["service"]
    if service_target == "both":
        targets = ["staff", "policy"]
    elif service_target == "policy":
        targets = ["policy"]
    elif service_target == "staff":
        targets = ["staff"]
    else:  # "none" — out of scope
        targets = []

    if targets:
        routing_reason = (
            f"Classified as {service_target} "
            f"({classification.get('confidence', 0):.0%} confidence)"
        )
    else:
        routing_reason = "Out of scope — not a staff or policy question."

    return {
        "target_services": targets,
        "classification": classification,
        "routing_reason": routing_reason,
    }
