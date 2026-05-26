"""Agent loop — Bedrock Converse with Tool Use, multi-turn.

Replaces detect_route + find_best_api + handler dispatch with a single agentic
loop. The LLM picks tools, the dispatcher runs them, results flow back to the
LLM until it emits a final text response for the user.

Public entry: `process_query_agent(user_question)` — drop-in for router's
process_query handlers.
"""
import json
import sys
import time

from config import (
    VERBOSE,
    MODEL_ID,
    GUARDRAILS,
    bedrock_runtime,
)
from state import user_context, conversation_history
from memory import _persist_turn, _format_user_profile
from style_guide import (
    AUSTRALIAN_ENGLISH,
    AUS_ENGLISH_BANNER,
    SOURCE_PRIVACY_PRINCIPLE,
    FORBIDDEN_PHRASES,
    IDENTITY_RULE,
    EMPTY_DATA_RULES,
    ANSWER_DIRECTLY,
    TIME_FORMAT_RULE,
)
from tools.registry import bedrock_tool_config
from tools.dispatcher import run_tool


# How many tool-call iterations to allow before giving up (prevents infinite loops).
_MAX_TOOL_ITERATIONS = 6

_IN_SCOPE_WORK_TERMS = (
    "shift",
    "shifts",
    "roster",
    "rosters",
    "client",
    "clients",
    "participant",
    "participants",
    "allowance",
    "allowances",
    "payroll",
    "ndis",
    "policy",
    "policies",
    "support worker",
    "support workers",
    "organisation",
    "organisations",
    "organization",
    "organizations",
    " org",
    "orgs",
    "business",
    "business name",
    "owner",
    "account",
)


def _looks_like_work_query(text):
    q = (text or "").lower()
    return any(term in q for term in _IN_SCOPE_WORK_TERMS)


def _work_query_snag_message(text):
    q = (text or "").lower()
    if (
        "organisation" in q or "organization" in q or " org" in q
        or "business" in q or "owner" in q or "account" in q
    ):
        subject = "organisation details"
    elif "client" in q or "participant" in q or "medical" in q:
        subject = "client information"
    elif "shift" in q or "roster" in q:
        subject = "shift answer"
    elif "payroll" in q or "allowance" in q:
        subject = "payroll details"
    elif "policy" in q or "ndis" in q:
        subject = "NDIS answer"
    else:
        subject = "answer"
    return (
        f"I hit a snag putting that {subject} together just now. "
        "Please try again in a moment."
    )


def _today_context_block():
    """Date/time context for the agent — uses the user's actual timezone.

    Pulls timezone from `state.current_timezone()` which reads from
    `user_context["timezone"]` (set by frontend OR by `set_my_timezone` tool)
    and falls back to Australia/Sydney when nothing is set.

    Includes a DST-aware footnote that the agent appends to any time-sensitive
    answer (shifts, dates, schedules). When fallback is in use, also invites
    the user to set their actual timezone.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from state import (
        current_timezone,
        user_context,
        timezone_observes_dst,
        timezone_dst_active_now,
        timezone_short_label,
    )

    tz_name = current_timezone()
    is_fallback = not (user_context.get("timezone") or "").strip()
    now = datetime.now(ZoneInfo(tz_name))
    short_label = timezone_short_label(tz_name)
    observes_dst = timezone_observes_dst(tz_name)
    dst_active = timezone_dst_active_now(tz_name)
    if dst_active:
        footnote_text = f"*(Based on {short_label} timezone with daylight saving)*"
    else:
        footnote_text = f"*(Based on {short_label} timezone)*"

    fallback_note = ""
    if is_fallback:
        fallback_note = (
            "\n"
            "TIMEZONE IS A FALLBACK — the user has NOT set their actual timezone yet.\n"
            "  - You computed everything in Australia/Sydney time.\n"
            "  - After answering ANY time-sensitive question (shifts, dates, schedules, "
            "    'today' / 'this week' / 'next month' etc.), APPEND a short, friendly note "
            "    on a new line — something like:\n"
            "    'Heads up — I used Sydney time since I don't know your actual timezone. "
            "    If you're in Perth, Brisbane, Adelaide, Melbourne, Hobart, or Darwin, "
            "    just tell me (\"I'm in Perth\") and I'll remember it.'\n"
            "  - DO NOT add this note on non-time-sensitive answers (policy questions, "
            "    profile lookups without dates, KB queries, etc.).\n"
            "  - When the user volunteers their location/timezone (\"I'm in Perth\", "
            "    \"my timezone is Brisbane\", \"I'm based in NSW\", etc.) → call the "
            "    `set_my_timezone` tool. After it returns, confirm briefly and offer to "
            "    re-run the previous time-sensitive query if there was one.\n"
        )

    return (
        f"Current date/time context (user's local time):\n"
        f"- Today is {now.strftime('%A, %d %B %Y')} ({tz_name}, {now.tzname()}).\n"
        f"- Current year: {now.year}. Current month: {now.strftime('%B')} ({now.month}).\n"
        f"- Timezone: {short_label}. Observes daylight saving: {'yes' if observes_dst else 'no'}. "
        f"DST currently active: {'yes' if dst_active else 'no'}.\n"
        f"- When the user says a month name without a year (e.g. 'May', 'in March'), "
        f"assume the CURRENT YEAR ({now.year}) unless they explicitly say otherwise.\n"
        f"- When the user says 'this week' / 'last week' / 'next week' / 'this month' / "
        f"'last month' / 'next month' / 'today' / 'yesterday' / 'tomorrow', compute "
        f"these relative to the date above in the user's local timezone.\n"
        f"- The backend API expects UTC; the shift/date tools handle that conversion "
        f"internally. You don't need to think about UTC — just reason in the user's "
        f"local time.\n"
        f"\n"
        f"## Timezone footnote — APPEND on time-sensitive replies\n"
        f"After ANY answer involving shifts, dates, schedules, times, or anything "
        f"sensitive to timezone (today/tomorrow/this week/this month/etc.), APPEND "
        f"this exact line on its own new line at the end of your reply (in italics):\n"
        f"    {footnote_text}\n"
        f"DO NOT add this footnote on non-time-sensitive answers (profile lookups "
        f"without dates, KB/policy queries, identity questions, error apologies, etc.). "
        f"Just the time-sensitive ones. The italics matter — keep the asterisks.\n"
        f"{fallback_note}"
    )


def _core_prompt():
    """Tier-1 system prompt — small, always included, cacheable.

    Holds the universals: identity, voice, today's date, source-privacy as a
    PRINCIPLE (no enumeration), forbidden phrases, empty-data rules. Anything
    domain-specific (shifts / clients / clinical / cross-client / staff /
    timezone) lives in conditional skill blocks loaded by _skills_for_question.
    """
    return f"""{AUS_ENGLISH_BANNER}

{AUSTRALIAN_ENGLISH}

{_today_context_block()}

You are the SENA NDIS assistant — for authenticated Australian NDIS workers (admins, in-office staff, support workers, ISWs, clients, guardians). You help with shifts, clients, staff, payroll, allowances, and NDIS policies.

## How you work
1. Read the user's question.
2. Pick the most appropriate tool — each tool's description tells you when to use it.
3. Look at the tool result.
4. Either chain another tool OR write the final answer.

Default to ACTION over clarification. If a sensible default exists (e.g. "shifts" → this_week), act on it. Only ask when truly ambiguous (e.g. 3 people share a name).

{SOURCE_PRIVACY_PRINCIPLE}

{FORBIDDEN_PHRASES}

{IDENTITY_RULE}

{EMPTY_DATA_RULES}

{ANSWER_DIRECTLY}

{TIME_FORMAT_RULE}

## Stay focused
When a tool returns useful data, write the answer — don't chain another tool unless genuinely needed.
"""


# ---- Conditional skill blocks (loaded per-question, NOT cached) ----

def _skill_shifts():
    return """## Shifts skill (active because the user mentioned shifts/meetings/sessions/etc.)

A SHIFT in SENA covers BOTH (a) participant support sessions AND (b) internal team meetings. Both are shifts — count and show both unless the user is explicit about which kind.

Tool: `list_my_shifts(timeframe=..., search=..., shift_filter=...)`
- Timeframes: today / tomorrow / yesterday / arvo / sarvo / this_week / next_week / last_week / this_month / next_month / last_month / date_range (needs from_date + to_date)
- `search="<name>"` to filter by participant or staff name
- `shift_filter="available"|"accepted"|"completed"` for status filter
- Admin org-wide view → `list_org_shifts`

Critical rules:
- "shifts" includes team meetings. Never say "no shifts" when team meetings exist.
- Filter to one kind ONLY when the user is unambiguously specific ("session with John" → participant only; "team huddle" → team meetings only).
- When both kinds are present, group them in the reply ("Sessions with participants" / "Team meetings"). When the user's question was generic, INCLUDE BOTH.
- A "meeting" / "session" / "appointment" / "visit" with a client = a shift. Always route through `list_my_shifts`.
- Month names without a year → use the year from your date context.
- A bare year follow-up ("in 2026") → re-run the previous shift query for that year via date_range.

## SHIFT RESULTS — multi-source merge (CRITICAL)

`list_my_shifts` returns DIFFERENT data shapes by persona:

**ADMIN persona** — multiple shift sources + clients reference (all in parallel):
- `data.shifts_thisweek` / `data.shifts_scheduled` / `data.shifts_completed` — `/organization/shift/list-view/type` (PRIMARY — authoritative shift list, type chosen from timeframe)
- `data.shifts_my_calendar` — `/organization-member/shift/calendar-view` (admin's own personal shifts as a member)
- `data.shifts_in_office` / `data.shifts_support_worker` / `data.shifts_clients_view` — picker-style endpoints; items MIGHT be shifts OR participants — inspect: items with `title`+`startTime`/`endTime` are SHIFTS, items with only `firstName`+`lastName` are participants and must be IGNORED for shift listings
- `data.clients_reference` — INTERNAL LOOKUP ONLY (see rule 5)

**Other personas** (support_worker / ISW / client / guardian):
- `data.shifts` — primary shift list (this-week-shifts fast path, or all-shifts)
- `data.shifts_calendar` — calendar-view (parallel fallback — `/mobile/{persona}-shift/calendar-view`). Returns shift occurrences in the asked range. If `data.shifts` is empty but `data.shifts_calendar` has data, the user has shifts; surface them.
- `data.clients_reference` — INTERNAL LOOKUP ONLY (not present for client/guardian personas)

Why 4 admin sources: the same shift can be visible from different angles — assigned in-office staff, assigned support workers, client participants, or the admin's own calendar. Querying only one returns empty when the data lives in another. We deliberately match the SENA UI's own approach.

**Rules:**

1. **Treat ALL shift sources as ONE unified list.** NEVER mention there were multiple sources. NEVER name "in_office" / "support_worker" / "clients_view" / "my_calendar" — internal plumbing the user must not see.

2. **Never say "no shifts" if ANY shift source has data in the asked window.** For admin: check `shifts_thisweek` / `shifts_scheduled` / `shifts_completed` / `shifts_my_calendar` / and any genuine shift items in the picker sources. For other personas: check BOTH `shifts` AND `shifts_calendar`. Saying "no shifts" while any source has data is the bug we're killing.

3. **Dedupe by shift id** if the same shift appears in multiple sources (very common for admin — the same shift shows up under in-office, support-worker, AND clients views).

4. **Cross-reference client ids against `clients_reference` SILENTLY.** When a shift has a client id but blank name/NDIS, look up the name in `clients_reference` and inline it ("Sat 09:00 with John Smith"). Never expose the lookup happened.

5. **NEVER MENTION `clients_reference` OR LIST CLIENTS UNLESS THE USER EXPLICITLY ASKED ABOUT CLIENTS.** Forbidden patterns when the user asked about SHIFTS:
   - "You've got 51 clients in your portfolio"
   - "You have N clients but no shifts in this window"
   - "Your clients are: …" (when they asked about shifts)
   - "Want me to check your client list?" (when they asked about shifts)
   - The clients_reference is a hidden lookup table — its size, contents, or existence MUST NOT leak into shift answers. If shifts are empty, just say "no shifts in [timeframe]" + offer a different timeframe. DO NOT mention client counts.

6. **When the user DOES explicitly ask about clients** ("how many clients do I have", "list my clients", "who are my participants") → THEN you may use `clients_reference` or call `list_my_clients` / `list_org_clients` and answer accordingly. Only then.

7. **For the pure client/participant persona**, only `data` (no source wrappers) is returned — single shift store, no clients list.
"""


def _skill_clients():
    return """## Client lookups skill (active because the user mentioned clients/participants/guardians)

- Name or ID mentioned ("tell me about Sarah", "client abc-123") → `find_person(query="<name>")` FIRST (backend search is fast). If exactly one match and the user wants the profile, follow with `get_client_details(client_id=<id>)`.
- "my clients" / "do I have clients" → `list_my_clients`.
- "all clients" / "every client" (admin) → `list_org_clients`.
- Cohort filters ("Aboriginal clients with autism in Sydney", "female clients under 21", "clients with allergies", "clients in Frankston") → `filter_clients_by_criteria` (admin/staff only). Use specific keys when obvious (`diagnosis`, `mobility`, `location`, `allergy`) and use `search` for anything broad or new.
- "[client]'s guardians" / "family contact for [client]" → `find_person` → `get_client_guardians(client_id=<id>)`.
- "who supports [client]" / "[client]'s support workers" → `find_person` → `get_client_support_workers(client_id=<id>)`.

NDIS events about a client are mostly captured as shifts. "What happened with [client] this week" / "sessions with [client] last month" → `list_my_shifts(search="<client>", timeframe=...)`. There is no direct case-note-by-client endpoint — be honest about this, then offer the shift-based alternative.

"client info for last month" (no specific person) → interpret as shifts with clients in that window → `list_my_shifts(timeframe="last_month")`.
"""


def _skill_clinical():
    return """## Clinical info skill (active because the user mentioned medications / allergies / risks / goals / support plan / diagnosis / medical history)

This IS core NDIS work — always allowed. Flow:

1. `find_person(query="<client name>")` → resolve to a client_id (or use known ID).
2. `get_client_details(client_id=<id>)` → full profile. Look at every plausible field for what the user asked — don't assume one specific key.
3. `get_policy(topic="<relevant topic>")` → the org's handling guidance from the KB. Pair the data with the policy.

Topic mapping for `get_policy`:
- medication questions → "medication management and administration"
- risk / fall / safety → "risk management and incident reporting"
- allergies → "allergy management protocol"
- support plan / care needs → "support plan delivery and duty of care"
- NDIS goals → "NDIS goal-oriented support delivery"
- medical history / diagnosis → "participant medical information handling"

Reply with TWO short blocks:
- A: the data (meds / risks / goals / allergies / etc. — listed factually from the profile)
- B: the org's policy paraphrased in plain Aussie English (never verbatim quote, never mention the KB)

If a field is missing/empty in the profile → "no X recorded" / "nothing on file for X". Never "field is null", "you need to log in", or "I don't have permission".

For cross-client clinical queries ("what meds do I need on hand for my clients") → call `list_my_clients()` first, then iterate `get_client_details` (cap at first 5; suggest the user names a specific client for full detail).
"""


def _skill_cross_client():
    return """## Cross-client skill (active because the user asked about "any of my clients" / "all" / "across")

The data IS available — either you've already fetched it, or call `list_my_clients` now. DO NOT refuse with "I can't pull this across clients".

For broad cohort/profile questions, prefer `filter_clients_by_criteria` with a broad `search` term unless the user only asked for a simple assigned-client list. The tool scans nested profile text, so it can handle medical info, primary diagnosis, location, mobility, allergies, medications, risks, support requirements, goals, and new profile fields without you guessing field names.

Distinguish THREE states clearly — never conflate them:
1. ASSIGNED — a real person/entity is mapped to the client (name/ID present).
2. DOCUMENTED — info is recorded (e.g. medication list filled in).
3. REQUIRED / NEEDED — support plan describes what they NEED but no provider is mapped.

Examples (PATTERNS, not data to copy):
- "Do any have a doctor?" → count clients with a name on file vs blank. Report real counts from THIS turn's tool output.
- "Support workers assigned?" → if mapping empty for all, say so. If support REQUIREMENTS are documented separately, mention as a different concept and offer a summary.

DATA RULES:
- Counts and names come from the most recent tool output. NEVER recall numbers from earlier turns if you don't currently have the data.
- NEVER reveal field names or data shapes. Plain English only: "no doctor recorded" / "no support worker assigned".
- If the user asks the same conceptual question twice, the answers MUST be consistent.
"""


def _skill_staff():
    return """## Staff lookups skill (active because the user mentioned staff / team / support workers / in-office / ISW)

- "All staff" / "team" / "in-office staff" / "support workers" → `list_org_staff`
  - `staff_type="in_office"` for in-office only
  - `staff_type="support_worker"` for support workers only
  - omit `staff_type` for everyone
- A staff member by name ("find Sarah in staff", "is John in-office") → `list_org_staff(search="<name>")` — backend matches case-insensitively on first / last / preferred name.
"""


def _skill_organizations():
    return """## Organisation lookup skill (active because the user mentioned organisations/orgs)

- "my organisations" / "my organizations" / "which orgs do I own" / "list my orgs" → `list_my_organizations`.
- This returns only the organisation IDs and business names linked to the logged-in owner.
"""


def _skill_timezone():
    return """## Timezone skill (active because the user mentioned a location / state / timezone)

If the user says "I'm in [location]" / "my timezone is X" / "I'm based in NSW" / similar → `set_my_timezone(timezone_or_location="<their input>")`.

After it saves, briefly confirm ("Got it — saved Perth time, I'll remember it") and OFFER to re-run the previous time-sensitive query. NEVER mention how long it's stored for.

If the resolver tool can't map the input, offer the user the friendly list: Sydney (NSW), Melbourne (VIC), Brisbane (QLD), Adelaide (SA), Perth (WA), Hobart (TAS), or Darwin (NT). Use simple language — no "IANA" or "timezone identifier" jargon.
"""


# Keyword triggers for each skill block. Lowercase substring match against
# the user's question. Over-triggering is fine (each block is small); the
# goal is to avoid loading a huge prompt for every turn.
_KW_SHIFT = (
    "shift", "meeting", "session", "appointment", "visit",
    "huddle", "standup", "today", "tomorrow", "yesterday",
    "this week", "next week", "last week",
    "this month", "next month", "last month",
    "arvo", "sarvo", "tonight", "tonite"
)
_KW_CLIENT = ("client", "participant", "guardian")
_KW_CLINICAL = (
    "medication", "meds", " med ", "allerg",
    "risk", "fall",
    "ndis goal", "goal",
    "doctor", " gp", "gp ", "diagnos",
    "support plan", "support requirement", "care plan",
    "medical", "history", "condition",
    "wheelchair", "wheel chair", "mobility", "walking aid",
    "asthma", "diabetes", "seizure", "epilepsy",
)
_KW_CROSS = (
    "any of", "across", "every client", "every clients",
    "all my", "all clients", "all of my",
    "do any", "how many of", "which clients",
)
_KW_STAFF = (
    "staff", "support worker", "in-office", "in office",
    "isw", "team", "huddle", "manager", "coordinator",
)
_KW_ORG = (
    "organisation", "organisations", "organization", "organizations",
    " org", "orgs", "business name", "owner",
)
_KW_TZ = (
    "timezone", "time zone", "i'm in ", "im in ",
    "based in", "located in", "my location",
    "set my time", "my time zone",
)
_AUS_LOCATIONS = (
    "sydney", "melbourne", "brisbane", "perth",
    "adelaide", "hobart", "darwin", "canberra",
    "nsw", "vic", "qld", "wa", "sa", "tas", "nt", "act",
)


def _skills_for_question(user_question: str) -> str:
    """Return the conditional skill blocks relevant to this question.
    Loads only what's needed — keeps the per-turn prompt lean.
    """
    if not user_question:
        return ""
    q = user_question.lower()
    parts = []

    if any(kw in q for kw in _KW_SHIFT):
        parts.append(_skill_shifts())
    if any(kw in q for kw in _KW_CLIENT):
        parts.append(_skill_clients())
    if any(kw in q for kw in _KW_CLINICAL):
        parts.append(_skill_clinical())
    if any(kw in q for kw in _KW_CROSS):
        parts.append(_skill_cross_client())
    if any(kw in q for kw in _KW_STAFF):
        parts.append(_skill_staff())
    if any(kw in q for kw in _KW_ORG):
        parts.append(_skill_organizations())
    if any(kw in q for kw in _KW_TZ) or any(loc in q for loc in _AUS_LOCATIONS):
        parts.append(_skill_timezone())

    return "\n\n".join(parts)


def _build_user_profile_block():
    """Tier-2 system prompt — per-user, cached separately."""
    return _format_user_profile()


def _bedrock_messages_from_history():
    """Convert the in-memory conversation_history into Bedrock messages format."""
    messages = []
    # Bedrock requires alternating user/assistant; the conversation_history is
    # already in role/content shape but may have multiple consecutive turns of
    # one role from streaming. Coalesce conservatively.
    for turn in conversation_history[-10:]:
        role = turn.get("role")
        if role not in ("user", "assistant"):
            continue
        content = turn.get("content") or []
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("text"):
                text_parts.append(part["text"])
        if not text_parts:
            continue
        messages.append({"role": role, "content": [{"text": "\n".join(text_parts)}]})
    return messages


def _content_blocks_with_tool_use(message):
    """Extract { text_blocks: [...], tool_use_blocks: [...] } from a Bedrock assistant message."""
    text_blocks = []
    tool_use_blocks = []
    for block in (message.get("content") or []):
        if "text" in block:
            text_blocks.append(block["text"])
        elif "toolUse" in block:
            tool_use_blocks.append(block["toolUse"])
    return text_blocks, tool_use_blocks


def process_query_agent(user_question):
    """Agentic processing of a user query.

    Returns the final string answer (already printed to the user via streaming
    or final reveal).
    """
    start = time.time()

    # Terminal-direct stream — bypasses Streamlit's redirect_stderr so the
    # launching shell always sees the agent's per-turn activity.
    _TERMINAL = sys.__stderr__
    print(f"\n[AGENT] ━━━ user: {user_question!r}", file=_TERMINAL, flush=True)

    # Tier 1 — small core prompt, cached (identity, voice, today, principles)
    system_blocks = [{"text": _core_prompt()}]
    system_blocks.append({"cachePoint": {"type": "default"}})

    # Tier 2 — per-user profile, cached per user
    profile_text = _build_user_profile_block()
    if profile_text:
        system_blocks.append({"text": profile_text})
        system_blocks.append({"cachePoint": {"type": "default"}})

    # Tier 3 — per-question skill blocks, NOT cached (varies per turn).
    # Only the relevant skills load — keeps the prompt lean per turn and
    # avoids feeding the LLM unrelated guidance that could trigger hallucination.
    skills_text = _skills_for_question(user_question)
    if skills_text:
        system_blocks.append({"text": skills_text})
        # Show which skill blocks were loaded for this turn
        skill_names = [line.split('(')[0].strip().replace('## ', '') for line in skills_text.split('\n') if line.startswith('## ')]
        print(f"[AGENT] skills loaded: {skill_names}", file=_TERMINAL, flush=True)
    else:
        print(f"[AGENT] skills loaded: [] (core prompt only)", file=_TERMINAL, flush=True)

    tool_config = bedrock_tool_config()

    # Seed messages: prior conversation + this new user turn
    messages = _bedrock_messages_from_history()
    messages.append({
        "role": "user",
        "content": [{"text": user_question}],
    })

    final_text = ""
    iterations = 0

    while iterations < _MAX_TOOL_ITERATIONS:
        iterations += 1
        loop_start = time.time()

        payload = {
            "modelId": MODEL_ID,
            "messages": messages,
            "system": system_blocks,
            "toolConfig": tool_config,
            "inferenceConfig": {"maxTokens": 2048},
        }

        # Primary guardrail rides on converse() — covers in + out, no extra cost
        if GUARDRAILS:
            primary_id, primary_ver = GUARDRAILS[0]
            payload["guardrailConfig"] = {
                "guardrailIdentifier": primary_id,
                "guardrailVersion": primary_ver,
                "trace": "enabled",
            }

        print(f"[AGENT] iter {iterations} → calling Bedrock...", file=_TERMINAL, flush=True)
        try:
            response = bedrock_runtime.converse(**payload)
        except Exception as e:
            print(f"[AGENT] ✗ Bedrock converse failed: {type(e).__name__}: {e}", file=_TERMINAL, flush=True)
            final_text = (
                "Sorry, I hit a snag connecting to the assistant just then. "
                "Give it another go in a moment."
            )
            break

        elapsed = time.time() - loop_start
        stop_reason = response.get("stopReason")
        # Show token usage so we can see prompt-size impact at a glance
        usage = response.get("usage") or {}
        in_tok = usage.get("inputTokens", 0)
        out_tok = usage.get("outputTokens", 0)
        cache_read = usage.get("cacheReadInputTokens", 0)
        cache_write = usage.get("cacheWriteInputTokens", 0)
        print(
            f"[AGENT] iter {iterations} done in {elapsed:.2f}s  stop={stop_reason}  "
            f"in={in_tok} (cache_r={cache_read}, cache_w={cache_write})  out={out_tok}",
            file=_TERMINAL, flush=True,
        )

        # Guardrail intervention — short-circuit
        if stop_reason == "guardrail_intervened":
            message = response.get("output", {}).get("message", {})
            text_blocks, _ = _content_blocks_with_tool_use(message)
            guardrail_text = " ".join(text_blocks).strip()
            if _looks_like_work_query(user_question):
                final_text = _work_query_snag_message(user_question)
            else:
                final_text = guardrail_text or (
                    "I can only help with SENA and NDIS-related questions. Please ask "
                    "about shifts, clients, payroll, policies, or other NDIS topics."
                )
            break

        assistant_message = response.get("output", {}).get("message", {})
        text_blocks, tool_use_blocks = _content_blocks_with_tool_use(assistant_message)

        # No tool calls → this is the final answer
        if stop_reason == "end_turn" or not tool_use_blocks:
            final_text = "\n".join(t for t in text_blocks if t).strip()
            if not final_text:
                final_text = "Sorry, I couldn't put together an answer for that."
            break

        # tool_use stop reason — append the assistant message and run each tool
        messages.append({
            "role": "assistant",
            "content": assistant_message.get("content") or [],
        })

        tool_result_blocks = []
        for tu in tool_use_blocks:
            tool_name = tu.get("name", "")
            tool_use_id = tu.get("toolUseId", "")
            tool_input = tu.get("input") or {}

            result = run_tool(tool_name, tool_input)

            tool_result_blocks.append({
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"json": result.to_dict()}],
                    "status": "error" if result.error else "success",
                }
            })

        messages.append({
            "role": "user",
            "content": tool_result_blocks,
        })

    if iterations >= _MAX_TOOL_ITERATIONS and not final_text:
        final_text = (
            "I worked through a few steps but couldn't wrap that one up neatly. "
            "Try rephrasing what you're after — for example: "
            "'show my shifts this week' or 'tell me about <client name>'."
        )

    total = time.time() - start
    reply_preview = final_text.replace("\n", " ")[:160]
    print(
        f"[AGENT] ━━━ done  {iterations} iter(s), {total:.2f}s total  "
        f"reply≈{reply_preview!r}",
        file=_TERMINAL, flush=True,
    )

    print(f"\nSena: {final_text}")
    _persist_turn(user_question, final_text, mode="AGENT")
    return final_text
