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
import asyncio
import logging
import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Any, Optional
# Bedrock free-text classification is DISABLED — routing is chip-driven (see
# route_query). boto3 imports kept commented for easy re-enable.
# import boto3
# from botocore.config import Config as BotoConfig

logger = logging.getLogger(__name__)


try:
    from dotenv import load_dotenv
    _here = Path(__file__).resolve()
    _staff_env = _here.parents[1] / "staff" / ".env"     # canonical key location
    for _cand in (
        Path.cwd() / ".env",
        _here.parent / ".env",                            # services/ai_chatbot/.env
        _here.parents[2] / ".env",                        # repo-root SENA/.env
        _staff_env,
    ):
        if _cand.is_file():
            load_dotenv(_cand, override=False)            # no break — accumulate keys
except ImportError:
    print("bedrock api not found", flush=True)

# ── Bedrock classification DISABLED (chip-driven routing only) ──────────────────
# _BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY", "")
# if _BEDROCK_API_KEY:
#     # setdefault: don't clobber a token already exported by the environment.
#     os.environ.setdefault("AWS_BEARER_TOKEN_BEDROCK", _BEDROCK_API_KEY)
#     logger.info("[router] using Bedrock API key (bearer token) from staff/.env")

# # Same region + active inference-profile model as the staff service, via the
# # Converse API (legacy claude-3-haiku invoke_model is access-denied here).
# REGION = "ap-southeast-2"
# MODEL_ID = "au.anthropic.claude-sonnet-4-5-20250929-v1:0"

# # ── Classification cache
# _CACHE_MAX = 1024            # max distinct questions cached
# _CACHE_TTL = 3600.0          # seconds before a cached label is considered stale
# _classify_cache: "OrderedDict[str, tuple[Dict[str, Any], float]]" = OrderedDict()
#
#
# def _cache_key(question: str) -> str:
#     return " ".join((question or "").lower().split())
#
#
# def _cache_get(question: str) -> Optional[Dict[str, Any]]:
#     key = _cache_key(question)
#     hit = _classify_cache.get(key)
#     if hit is None:
#         return None
#     value, ts = hit
#     if (time.monotonic() - ts) > _CACHE_TTL:
#         _classify_cache.pop(key, None)
#         return None
#     _classify_cache.move_to_end(key)  # mark most-recently-used
#     return dict(value)
#
#
# def _cache_put(question: str, value: Dict[str, Any]) -> None:
#     key = _cache_key(question)
#     _classify_cache[key] = (dict(value), time.monotonic())
#     _classify_cache.move_to_end(key)
#     while len(_classify_cache) > _CACHE_MAX:
#         _classify_cache.popitem(last=False)  # evict least-recently-used

# ── UI chip → service + scope (instant, no LLM) ─────────────────────────────────
# The frontend sends a `category` when a chip is tapped. Each chip maps to a
# backend service AND a scope hint that nudges the staff agent toward the right
# tool group (tools/staff, tools/clients) — plus a seed question for a bare tap.
#
#   Check Shifts         → staff  (tools/staff:  shifts, staff filter)
#   Client's information → staff  (tools/clients: details, medical, meds, search)
#   Policies             → policy (policy_proc pipeline)
#   Procedures           → policy (policy_proc pipeline)
# `agent_scope` selects the staff service's INDEPENDENT section endpoint:
#   "staff"  → POST /staff/query/stream   (shifts/rosters/team)
#   "client" → POST /client/query/stream  (participant info)
# The two are isolated server-side, so a "shifts" chip can never reach client data.
_CATEGORY_DEFS = {
    "shifts": {
        "service": "staff",
        "agent_scope": "staff",
        "scope": "staff and shift information (rosters, shift times, team members)",
        "seed": "What are my shifts?",
    },
    "client": {
        "service": "staff",
        "agent_scope": "client",
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


# ── Bedrock client ──────
# _bedrock_client = None
#
#
# def get_bedrock_client():
#     """Lazy-load Bedrock runtime client with a tuned connection pool.
#
#     - keep-alive connection pool (max_pool_connections) so concurrent classify
#       calls reuse TCP/TLS instead of re-handshaking;
#     - adaptive retries to ride out transient throttling without manual backoff;
#     - tight connect/read timeouts so a stalled call fails fast instead of
#       holding a worker.
#     """
#     global _bedrock_client
#     if _bedrock_client is None:
#         _bedrock_client = boto3.client(
#             "bedrock-runtime",
#             region_name=REGION,
#             config=BotoConfig(
#                 max_pool_connections=32,
#                 retries={"max_attempts": 3, "mode": "adaptive"},
#                 connect_timeout=3,
#                 read_timeout=12,
#             ),
#         )
#     return _bedrock_client
#
#
# _SYSTEM_PROMPT = """You route questions for an NDIS (Australian disability services) staff assistant to ONE service. Decide from MEANING — handle typos, slang and terse phrasing; never rely on exact keywords.
#
# Services:
# - "staff": the worker's own work and identity. Covers:
#     • shifts, rosters, payroll, payslips, allowances, timesheets, leave balances/requests, availability;
#     • CLIENTS — who their clients are, client details, care, medical/medication/support info, client schedules, client search;
#     • profile/identity/memory/time — "who am I", "my profile", "remember my name", "what do you know about me", "set my timezone", "what time is it", "my organisations".
#   "my clients", "who are my clients", "client information" are ALWAYS staff. General/personal questions the assistant can answer about the user are staff.
# - "policy": ANYTHING about policy, compliance, procedures, rules, guidelines, restrictive practices, codes of conduct, NDIS standards/legislation, what is/isn't allowed or required, how to handle/report something — INCLUDING when it concerns staff or clients (e.g. "staff leave policy", "client confidentiality policy", "am I allowed to give a client medication", "what should I do if a client falls"). If the question is about a rule, permission, obligation or correct procedure, it is "policy" even with no literal policy word and even when it mentions staff/clients.
# - "both": genuinely needs the worker's OWN data AND a policy rule together (e.g. "can I take leave during my rostered shift?").
# - "none": clearly unrelated to NDIS work and not about the user's own profile — bare greetings, weather, sport, recipes, math, general chit-chat.
#
# Priority when a query has both a personal/operational angle AND a rule/permission angle: if it asks what is allowed/required or how to follow a procedure → "policy". Otherwise → "staff".
#
# Examples:
# Q: "who are my cloents" → staff
# Q: "what are my shifts this week" → staff
# Q: "my payroll" → staff
# Q: "client information for John" → staff
# Q: "clients with autism" → staff
# Q: "remember my name is Jake" → staff
# Q: "what time is it" → staff
# Q: "who am I" → staff
# Q: "what is the leave policy" → policy
# Q: "staff leave policy" → policy
# Q: "client confidentiality policy" → policy
# Q: "am I allowed to restrain a client" → policy
# Q: "what should I do if a client falls" → policy
# Q: "what procedures must I follow" → policy
# Q: "can I take leave during my shift" → both
# Q: "what's the weather" → none
# Q: "hi" → none
# Q: "2+2" → none
#
# Respond with ONLY a JSON object, no prose:
# {"service":"staff|policy|both|none","confidence":0.0-1.0,"reason":"short","priority":"staff|policy"}"""
#
#
# def _bedrock_classify_sync(question: str, model_id: str) -> Dict[str, Any]:
#     """Blocking Bedrock classify call. Run via asyncio.to_thread (see below)."""
#     client = get_bedrock_client()
#     resp = client.converse(
#         modelId=model_id,
#         system=[{"text": _SYSTEM_PROMPT}],
#         messages=[{"role": "user", "content": [{"text": f"Q: {question}"}]}],
#         inferenceConfig={"maxTokens": 200, "temperature": 0},
#     )
#     text = "".join(
#         b["text"] for b in resp["output"]["message"]["content"] if "text" in b
#     ).strip()
#     start, end = text.find("{"), text.rfind("}")
#     data = json.loads(text[start:end + 1] if start != -1 else text)
#     service = data.get("service", "staff")
#     if service not in ("staff", "policy", "both", "none"):
#         service = "staff"
#     return {
#         "service": service,
#         "confidence": float(data.get("confidence", 0.5)),
#         "reason": data.get("reason", ""),
#         "priority": data.get("priority", "staff"),
#     }
#
#
# async def classify_query(
#     question: str,
#     model_id: str = MODEL_ID,
# ) -> Dict[str, Any]:
#     """Classify a free-text query dynamically via Bedrock.
#
#     Performance:
#       • deterministic (temp=0) → results are LRU-cached, so repeat questions
#         skip Bedrock entirely (0 latency, 0 cost);
#       • the blocking boto3 call runs in a worker thread (asyncio.to_thread) so it
#         NEVER stalls the event loop — other concurrent requests keep flowing.
#
#     Returns: {"service": "staff|policy|both|none", "confidence": float,
#               "reason": str, "priority": "staff|policy"}.
#     """
#     if not (question or "").strip():
#         return {"service": "none", "confidence": 1.0,
#                 "reason": "Empty question.", "priority": "staff"}
#
#     cached = _cache_get(question)
#     if cached is not None:
#         cached["cached"] = True
#         return cached
#
#     try:
#         # Offload the synchronous boto3 call to a thread → event loop stays free.
#         result = await asyncio.to_thread(_bedrock_classify_sync, question, model_id)
#         _cache_put(question, result)
#         return result
#     except (json.JSONDecodeError, ValueError) as e:
#         # Parse failure is rare; don't silently drop a likely-valid query —
#         # default to staff (the primary work surface) rather than "none".
#         logger.warning(f"Failed to parse classifier response: {e}")
#         return {"service": "staff", "confidence": 0.3,
#                 "reason": "Unparseable classifier output; defaulting to staff.",
#                 "priority": "staff"}
#     except Exception as e:
#         logger.exception(f"Bedrock classification failed: {e}")
#         return {"service": "none", "confidence": 0.0,
#                 "reason": f"Classifier error: {e}", "priority": "staff"}


# Human-readable label for each chip (what the user taps in the UI).
_SECTION_LABEL = {
    "shifts": "Check Shifts",
    "client": "Client's information",
    "policy": "Policies",
    "procedure": "Procedures",
}

# Topics that DON'T belong in a section ("blocked"), each mapped to the section it
# DOES belong in — so we can tell the user exactly which option to switch to.
# Order matters: longer/more-specific phrases first ("my client" before "client").
_BLOCKED_BY_SECTION: dict[str, list[tuple[str, str]]] = {
    "shifts": [
        ("medication", "client"), ("support worker", "client"), ("guardian", "client"),
        ("carer", "client"), ("client", "client"),
    ],
    "client": [
        ("roster", "shifts"), ("schedule", "shifts"), ("time off", "shifts"),
        ("hours", "shifts"), ("shift", "shifts"),
    ],
    "policy": [
        ("my shift", "shifts"), ("my client", "client"), ("shift", "shifts"), ("client", "client"),
    ],
    "procedure": [
        ("my shift", "shifts"), ("my client", "client"), ("shift", "shifts"), ("client", "client"),
    ],
}


def _check_scope_enforcement(question: str, chip_category: str) -> Optional[str]:
    """Check whether a typed question fits the tapped chip's section.

    The staff and client sections (and policy/procedure) are independent — there is
    no cross-section answering. Returns None if the question fits; otherwise a
    DIRECTIVE message telling the user exactly which section to switch to.
    """
    if not question or not chip_category:
        return None

    q_lower = question.lower()
    blocked = _BLOCKED_BY_SECTION.get(chip_category)
    if not blocked:
        return None  # Unknown chip — allow.

    current = _SECTION_LABEL.get(chip_category, chip_category)
    for word, home in blocked:
        if word in q_lower:
            target = _SECTION_LABEL.get(home, home)
            return (
                f"That looks like a “{target}” question, but you're in the "
                f"“{current}” section. These sections are kept separate — please "
                f"switch to “{target}” to ask about that."
            )

    return None  # In scope.


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
            # Sub-scope for the staff service's independent endpoints (None for policy).
            "staff_scope": cat.get("agent_scope"),
        }

    # ── Free-text classification — DISABLED ──────────────────────────────────────
    # The frontend uses the chip-selector, so every request arrives with a
    # `category`. Free-text Bedrock classification is intentionally turned off
    # (no chip → out of scope). To re-enable, restore the block below.
    #
    # classification = await classify_query(question)
    # service_target = classification["service"]
    # if service_target == "both":
    #     targets = ["staff", "policy"]
    # elif service_target == "policy":
    #     targets = ["policy"]
    # elif service_target == "staff":
    #     targets = ["staff"]
    # else:  # "none" — out of scope
    #     targets = []
    # if targets:
    #     routing_reason = (
    #         f"Classified as {service_target} "
    #         f"({classification.get('confidence', 0):.0%} confidence)"
    #     )
    # else:
    #     routing_reason = "Out of scope — not a staff or policy question."
    # return {
    #     "target_services": targets,
    #     "classification": classification,
    #     "routing_reason": routing_reason,
    #     "question": question,
    #     "staff_scope": None,
    # }

    reason = "Please choose a section (Shifts, Client, Policies, or Procedures) to ask your question."
    return {
        "target_services": [],
        "classification": {
            "service": "none", "confidence": 1.0,
            "reason": reason, "priority": "staff",
        },
        "routing_reason": reason,
        "question": question,
        "staff_scope": None,
    }
