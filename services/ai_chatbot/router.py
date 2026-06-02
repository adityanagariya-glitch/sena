"""Query classification + routing for the SENA ai_chatbot gateway.

Two ways a query reaches a backend service:

  1. category hint  — the frontend taps a chip ("Policies", "Check Shifts",
     "Procedures", "Client's information"). That maps DIRECTLY to a service and
     scopes the staff agent to the right tool group. No LLM call.

  2. free text      — the user types a question. Bedrock (Claude, Converse API)
     classifies it DYNAMICALLY from meaning — no keyword/regex lists. It handles
     typos, terse phrasing, and semantic policy intent ("am I allowed to…") on
     its own.

Services:
  • "staff"  — the worker's own work + identity: shifts, rosters, payroll,
    allowances, timesheets, leave balances, their CLIENTS (details, medical,
    meds, support, search), and profile/meta (who am I, remember me, time).
  • "policy" — anything about policy/compliance/procedures/rules — INCLUDING
    policy questions about staff or clients ("staff leave policy"). policy_proc.
"""
import logging
import json
from typing import Dict, Any, Optional
import boto3

logger = logging.getLogger(__name__)

# Same region + active inference-profile model as the staff service, via the
# Converse API (legacy claude-3-haiku invoke_model is access-denied here).
REGION = "ap-southeast-2"
MODEL_ID = "au.anthropic.claude-sonnet-4-6"

# ── UI chip → service + scope (instant, no LLM) ─────────────────────────────────
# The frontend sends a `category` when a chip is tapped. Each chip maps to a
# backend service AND a scope hint that nudges the staff agent toward the right
# tool group (tools/staff, tools/clients) — plus a seed question for a bare tap.
#
#   Check Shifts         → staff  (tools/staff:  shifts, staff filter)
#   Client's information → staff  (tools/clients: details, medical, meds, search)
#   Policies             → policy (policy_proc pipeline)
#   Procedures           → policy (policy_proc pipeline)
_CATEGORY_DEFS = {
    "shifts": {
        "service": "staff",
        "scope": "staff and shift information (rosters, shift times, team members)",
        "seed": "What are my shifts?",
    },
    "client": {
        "service": "staff",
        "scope": "client information only — client details, medical info, medications, "
                 "support workers, guardians, and client search/filter",
        "seed": "Who are my clients?",
    },
    "policy": {
        "service": "policy",
        "scope": "organisational policy",
        "seed": "What policies apply to me?",
    },
    "procedure": {
        "service": "policy",
        "scope": "compliance procedures",
        "seed": "What procedures must I follow?",
    },
}
_CATEGORY_ALIASES = {
    "shift": "shifts", "shifts": "shifts", "check shifts": "shifts", "staff": "shifts",
    "client": "client", "clients": "client", "client information": "client",
    "clients information": "client", "client's information": "client",
    "clients' information": "client",
    "policy": "policy", "policies": "policy",
    "procedure": "procedure", "procedures": "procedure", "compliance": "procedure",
}


def _norm_category(category: str) -> str:
    return (category or "").strip().lower().replace("’", "'").replace("'", "")


def resolve_category(category: str) -> Optional[Dict[str, str]]:
    """Map a UI chip/category to its definition {service, scope, seed}, or None."""
    if not category:
        return None
    key = _CATEGORY_ALIASES.get(_norm_category(category)) \
        or _CATEGORY_ALIASES.get(category.strip().lower())
    return _CATEGORY_DEFS.get(key) if key else None


def route_category(category: str) -> Optional[str]:
    """Map a UI chip/category to a service ('staff'|'policy'), or None if unknown."""
    d = resolve_category(category)
    return d["service"] if d else None


# ── Bedrock client ──────────────────────────────────────────────────────────────
_bedrock_client = None


def get_bedrock_client():
    """Lazy-load Bedrock runtime client."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-runtime", region_name=REGION)
    return _bedrock_client


_SYSTEM_PROMPT = """You route questions for an NDIS (Australian disability services) staff assistant to ONE service. Decide from MEANING — handle typos, slang and terse phrasing; never rely on exact keywords.

Services:
- "staff": the worker's own work and identity. Covers:
    • shifts, rosters, payroll, payslips, allowances, timesheets, leave balances/requests, availability;
    • CLIENTS — who their clients are, client details, care, medical/medication/support info, client schedules, client search;
    • profile/identity/memory/time — "who am I", "my profile", "remember my name", "what do you know about me", "set my timezone", "what time is it", "my organisations".
  "my clients", "who are my clients", "client information" are ALWAYS staff. General/personal questions the assistant can answer about the user are staff.
- "policy": ANYTHING about policy, compliance, procedures, rules, guidelines, restrictive practices, codes of conduct, NDIS standards/legislation, what is/isn't allowed or required, how to handle/report something — INCLUDING when it concerns staff or clients (e.g. "staff leave policy", "client confidentiality policy", "am I allowed to give a client medication", "what should I do if a client falls"). If the question is about a rule, permission, obligation or correct procedure, it is "policy" even with no literal policy word and even when it mentions staff/clients.
- "both": genuinely needs the worker's OWN data AND a policy rule together (e.g. "can I take leave during my rostered shift?").
- "none": clearly unrelated to NDIS work and not about the user's own profile — bare greetings, weather, sport, recipes, math, general chit-chat.

Priority when a query has both a personal/operational angle AND a rule/permission angle: if it asks what is allowed/required or how to follow a procedure → "policy". Otherwise → "staff".

Examples:
Q: "who are my cloents" → staff
Q: "what are my shifts this week" → staff
Q: "my payroll" → staff
Q: "client information for John" → staff
Q: "clients with autism" → staff
Q: "remember my name is Jake" → staff
Q: "what time is it" → staff
Q: "who am I" → staff
Q: "what is the leave policy" → policy
Q: "staff leave policy" → policy
Q: "client confidentiality policy" → policy
Q: "am I allowed to restrain a client" → policy
Q: "what should I do if a client falls" → policy
Q: "what procedures must I follow" → policy
Q: "can I take leave during my shift" → both
Q: "what's the weather" → none
Q: "hi" → none
Q: "2+2" → none

Respond with ONLY a JSON object, no prose:
{"service":"staff|policy|both|none","confidence":0.0-1.0,"reason":"short","priority":"staff|policy"}"""


async def classify_query(
    question: str,
    model_id: str = MODEL_ID,
) -> Dict[str, Any]:
    """Classify a free-text query dynamically via Bedrock.

    Returns: {"service": "staff|policy|both|none", "confidence": float,
              "reason": str, "priority": "staff|policy"}.
    """
    if not (question or "").strip():
        return {"service": "none", "confidence": 1.0,
                "reason": "Empty question.", "priority": "staff"}
    try:
        client = get_bedrock_client()
        resp = client.converse(
            modelId=model_id,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": f"Q: {question}"}]}],
            inferenceConfig={"maxTokens": 200, "temperature": 0},
        )
        text = "".join(
            b["text"] for b in resp["output"]["message"]["content"] if "text" in b
        ).strip()

        try:
            start, end = text.find("{"), text.rfind("}")
            data = json.loads(text[start:end + 1] if start != -1 else text)
            service = data.get("service", "staff")
            if service not in ("staff", "policy", "both", "none"):
                service = "staff"
            return {
                "service": service,
                "confidence": float(data.get("confidence", 0.5)),
                "reason": data.get("reason", ""),
                "priority": data.get("priority", "staff"),
            }
        except (json.JSONDecodeError, ValueError):
            # Parse failure is rare; don't silently drop a likely-valid query —
            # default to staff (the primary work surface) rather than "none".
            logger.warning(f"Failed to parse classifier response: {text!r}")
            return {"service": "staff", "confidence": 0.3,
                    "reason": "Unparseable classifier output; defaulting to staff.",
                    "priority": "staff"}
    except Exception as e:
        logger.exception(f"Bedrock classification failed: {e}")
        return {"service": "none", "confidence": 0.0,
                "reason": f"Classifier error: {e}", "priority": "staff"}


def _check_scope_enforcement(question: str, chip_category: str) -> Optional[str]:
    """Check if a typed question is within the scope of the tapped chip.

    Returns None if in scope, otherwise returns a rejection reason.
    """
    if not question or not chip_category:
        return None

    q_lower = question.lower()

    # Define scope rules: chip → (allowed_keywords, blocked_keywords)
    scope_rules = {
        "shifts": {
            "allowed": ["shift", "roster", "schedule", "time off", "hours", "when", "working", "swap", "rota"],
            "blocked": ["client", "medication", "support worker", "guardian", "carer"],
        },
        "client": {
            "allowed": ["client", "medication", "medical", "support worker", "guardian", "carer", "diagnosis", "care plan"],
            "blocked": ["shift", "roster", "schedule", "hours", "time off"],
        },
        "policy": {
            "allowed": ["policy", "allowed", "permit", "rule", "procedure", "compliance", "standard"],
            "blocked": ["shift", "client", "my shift", "my client"],
        },
        "procedure": {
            "allowed": ["procedure", "report", "process", "how", "incident", "safeguard", "training"],
            "blocked": ["shift", "client", "my shift", "my client"],
        },
    }

    rules = scope_rules.get(chip_category)
    if not rules:
        return None  # Unknown chip, allow

    # Check for blocked keywords
    for word in rules.get("blocked", []):
        if word in q_lower:
            return f"Out of scope for '{chip_category}' section. Please stay within {chip_category} questions."

    return None  # In scope


async def route_query(
    question: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Route a query to service(s).

    If context carries a "category" (UI chip tap), it maps directly to a service
    with no LLM call and scopes the staff agent. Otherwise the free-text question
    is classified dynamically by Bedrock.

    Returns: {"target_services": [...], "classification": {...},
              "routing_reason": str, "question": <effective question to send>}
    """
    # Chip / category shortcut — instant, deterministic, tool-scoped.
    category = (context or {}).get("category")
    cat = resolve_category(category) if category else None
    if cat:
        # If a question was typed (not just bare chip tap), enforce scope
        if question and (question or "").strip():
            scope_error = _check_scope_enforcement(question, category)
            if scope_error:
                return {
                    "target_services": [],
                    "classification": {
                        "service": "none",
                        "confidence": 1.0,
                        "reason": scope_error,
                        "priority": "staff",
                    },
                    "routing_reason": scope_error,
                    "question": question,
                }

        service = cat["service"]
        eff_q = (question or "").strip() or cat["seed"]
        # For staff, prepend a soft scope so the agent picks the right tool group.
        effective_question = (
            f"Regarding {cat['scope']}: {eff_q}" if service == "staff" else eff_q
        )
        classification = {
            "service": service, "confidence": 1.0,
            "reason": f"Category '{category}' → {service} ({cat['scope']})",
            "priority": service,
        }
        return {
            "target_services": [service],
            "classification": classification,
            "routing_reason": f"Category '{category}' routed to {service}.",
            "question": effective_question,
        }

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
        "question": question,
    }
