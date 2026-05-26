"""API routing: intent detection, choosing the right API, calling it, access control."""
import json
import re
import requests

from config import API_BASE_URL, BEDROCK_KB_ID
from state import (
    user_context,
    conversation_history,
    COMMON_APIS,
    CLIENT_APIS,
    STAFF_APIS,
)
from auth import get_auth_headers, has_auth_token
from bedrock_client import call_bedrock


def _format_api_section(title, apis, start_idx=1):
    """Render one section of APIs (numbered list with method+path+params)."""
    if not apis:
        return "", start_idx
    text = f"### {title}\n"
    for i, api in enumerate(apis, start_idx):
        method = api.get('method', 'GET')
        path = api.get('path', '')
        description = api.get('description', '')
        text += f"{i}. {method} {path}\n"
        text += f"   {description}\n"

        if api.get('parameters'):
            params_str = ", ".join([f"{p.get('name', '')} ({p.get('type', '')})" for p in api['parameters']])
            text += f"   Parameters: {params_str}\n"
        text += "\n"
    return text, start_idx + len(apis)


def get_api_description():
    """Create formatted description of APIs available to the current user.

    Groups output by section (Staff / Client / Common) so the LLM can scan
    the relevant section quickly. Filters by user role inline — client/guardian
    personas only see CLIENT + COMMON; staff/admin/isw see STAFF + CLIENT + COMMON.
    """
    user_type = (user_context.get("user_type") or "").lower()
    staff_type = (user_context.get("staff_type") or "").lower()
    roles = [r.lower() for r in (user_context.get("roles") or [])]

    is_client_persona = user_type in ("client", "guardian") or "guardian" in roles

    api_text = "Available APIs (organized by section):\n\n"
    idx = 1

    # Staff section — only shown to non-client personas
    if not is_client_persona:
        section_text, idx = _format_api_section("Staff APIs (shifts, payroll, allowances)", STAFF_APIS, idx)
        api_text += section_text

    # Client section — visible to everyone (staff need to look up clients, clients need their own data)
    section_text, idx = _format_api_section("Client APIs (profiles, agreements, documents)", CLIENT_APIS, idx)
    api_text += section_text

    # Common section — shared org-level lookups
    section_text, idx = _format_api_section("Common APIs (roles, profiles, org lookups)", COMMON_APIS, idx)
    api_text += section_text

    return api_text


def detect_route(user_question):
    """Unified router: intent + multi-source detection in ONE Bedrock call.

    Replaces the separate detect_intent + detect_hybrid_intent pair. Caller
    branches on `needs_api`/`needs_kb`/`needs_meta` (2+ flags → hybrid path,
    1 flag → matches `intent`, 0 flags → intent=CHAT). `find_best_api` is
    still called separately downstream for any API-needing path.

    Returns dict:
      needs_api, needs_kb, needs_meta: bool
      intent: "API"|"KB"|"META"|"CHAT"  (primary single-source intent)
      api_question, kb_question, meta_question: standalone sub-questions
      reason: str
    """
    kb_available = "yes" if BEDROCK_KB_ID else "no"

    recent_context = ""
    if conversation_history:
        snippets = []
        for turn in conversation_history[-4:]:
            role = turn.get("role", "").upper()
            for part in turn.get("content", []) or []:
                if isinstance(part, dict) and part.get("text"):
                    text = part["text"]
                    if len(text) > 400:
                        text = text[:400] + "…"
                    snippets.append(f"{role}: {text}")
        if snippets:
            recent_context = "\n\nRecent conversation (for disambiguation only):\n" + "\n".join(snippets)

    system_prompt = f"""You are routing a SENA NDIS assistant request. Decide which information source(s) the user's single message needs.

User: type={user_context['user_type']}, roles={user_context['roles']}, org={user_context['organization_id']}.
Knowledge base available: {kb_available}.{recent_context}

Sources:
1. API — live application data: shifts, rosters, clients, staff, payroll, allowances, schedules, organisation records, support workers, guardians, incidents.
2. KB  — documented knowledge: policies, procedures, requirements, standards, rules, compliance, code of conduct, privacy, NDIS practice standards, training material.
3. META — conversation memory across THIS session AND prior sessions: what the user asked earlier, what was previously answered, "you said", "earlier", "before", "previous", "remind me", "last session", "last time", "what did we talk about", "what did I ask yesterday". The assistant has access to prior-session summaries via long-term memory, so don't treat "last session" as out-of-scope.
4. CHAT — small talk, greetings, AND IMPORTANTLY: profile/identity questions about the logged-in user themselves ("what is my role", "who am I", "what's my email", "my user type", "my permissions"). These are answered from the user's own profile (already loaded), NOT from an API call.

Return JSON only:
{{
  "needs_api": true|false,
  "needs_kb": true|false,
  "needs_meta": true|false,
  "intent": "API|KB|META|CHAT",
  "wants_fresh_data": true|false,
  "api_question": "<standalone sub-question for live data, or empty>",
  "kb_question": "<standalone sub-question for documented knowledge, or empty>",
  "meta_question": "<standalone sub-question for conversation memory, or empty>",
  "reason": "<brief>"
}}

`wants_fresh_data` is true ONLY when the user is explicitly asking for an updated/refreshed/current version of data they already saw (e.g. "refresh", "latest", "now", "again, but newer", "anything changed?"). Default to false. Same question asked again WITHOUT a freshness keyword is NOT a freshness request — it should reuse cached data.

Rules:
- Memory-first: ONLY if the user uses explicit recall keywords ("you said", "earlier", "before", "previous", "remind me", "what did we talk about", "last time", "remember when"), set needs_meta=true AND intent=META. Past-tense framing alone is NOT enough — require the keyword.
- Otherwise, set exactly one needs_* flag for single-source asks and match `intent` to it. Set 2+ flags for multi-source asks (intent should be the primary one).
- If no data sources are needed (greetings, small talk, generic chat), set all needs_* to false AND intent=CHAT.
- Infer KB need from intent words like "what should I follow", "is that allowed", "what are the requirements", "compliance", "policy" — topic overlap with prior answers does NOT mean the answer is in memory.
- Preserve date/time/entity details in sub-questions, including typos like "tommow".
- If knowledge base is not available, never set needs_kb=true or intent=KB.
- Default bias: when in doubt between API and META, choose API — re-fetch is safer than returning stale information.

Examples:
User: "what is my shift tomorrow"
{{"needs_api": true, "needs_kb": false, "needs_meta": false, "intent": "API", "api_question": "what is my shift tomorrow", "kb_question": "", "meta_question": "", "reason": "live shift data"}}

User: "what is the cancellation policy"
{{"needs_api": false, "needs_kb": true, "needs_meta": false, "intent": "KB", "api_question": "", "kb_question": "what is the cancellation policy", "meta_question": "", "reason": "documented policy"}}

User: "what is my shift tommow and what is it policy"
{{"needs_api": true, "needs_kb": true, "needs_meta": false, "intent": "API", "api_question": "what is my shift tommow", "kb_question": "what policy or procedure applies to my shift tommow?", "meta_question": "", "reason": "shift data and related policy"}}

User: "what is my shift tomorrow and what did you tell me earlier about breaks"
{{"needs_api": true, "needs_kb": false, "needs_meta": true, "intent": "API", "api_question": "what is my shift tomorrow", "kb_question": "", "meta_question": "what did you tell me earlier about breaks?", "reason": "live shift data and prior conversation"}}

User: "what did I ask earlier"
{{"needs_api": false, "needs_kb": false, "needs_meta": true, "intent": "META", "api_question": "", "kb_question": "", "meta_question": "what did I ask earlier?", "reason": "conversation memory"}}

User: "hi"
{{"needs_api": false, "needs_kb": false, "needs_meta": false, "intent": "CHAT", "api_question": "", "kb_question": "", "meta_question": "", "reason": "greeting"}}

User: "what is my role"
{{"needs_api": false, "needs_kb": false, "needs_meta": false, "intent": "CHAT", "api_question": "", "kb_question": "", "meta_question": "", "reason": "profile question — answered from user_context, no API"}}

User: "who am I"
{{"needs_api": false, "needs_kb": false, "needs_meta": false, "intent": "CHAT", "api_question": "", "kb_question": "", "meta_question": "", "reason": "identity question — profile info already loaded"}}"""

    messages = [{"role": "user", "content": [{"text": user_question}]}]
    # Internal routing classifier — output is JSON, not user-facing, skip guardrails
    response = call_bedrock(messages, system_prompt, use_guardrail=False)
    if not response:
        return {"needs_api": False, "needs_kb": False, "needs_meta": False, "intent": "CHAT", "wants_fresh_data": False, "reason": "no response"}

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            decision = json.loads(json_match.group())
            if isinstance(decision, dict):
                # Force kb off if KB not configured (model occasionally ignores the rule).
                if not BEDROCK_KB_ID:
                    decision["needs_kb"] = False
                    if decision.get("intent") == "KB":
                        decision["intent"] = "CHAT"
                return decision
    except Exception:
        pass

    return {"needs_api": False, "needs_kb": False, "needs_meta": False, "intent": "CHAT", "wants_fresh_data": False, "reason": "parse error"}


def find_best_api(user_question):
    """Use LLM to determine which API to call"""
    user_type = user_context.get('user_type', 'unknown')
    org_id = user_context.get('organization_id')

    context_notes = ""
    staff_type = user_context.get("staff_type", "")
    if user_type == "admin" and not org_id:
        context_notes = """
IMPORTANT CONTEXT — This user is a SUPER ADMIN (platform-level):
- They are NOT a member of any organization (organizationId is None)
- DO NOT use /organization-member/* or /mobile/* endpoints (those need org membership; will return 401)
- For shifts/staff/clients: use /organization/* endpoints (admin-wide org views)
- For their own profile: use /super-admin/get-profile
- For roles/permissions: use /sena-admin-role/*
- If they ask about "my shifts" — they have no personal shifts; explain that or list org-wide shifts instead
"""
    elif user_type == "admin" and org_id:
        context_notes = f"""
IMPORTANT CONTEXT — This user is an IN-OFFICE ORG MEMBER (admin-level within org):
- staffType: {staff_type}, organizationId: {org_id}
- For "my shifts" / personal data: use /organization-member/* endpoints
- For org-wide views (all shifts/staff/clients): use /organization/* endpoints
- DO NOT use /super-admin/* (this is org-scoped, not platform-scoped)
- DO NOT use /mobile/* (those are for the mobile app field staff)
"""
    elif user_type == "staff" and org_id:
        context_notes = f"""
IMPORTANT CONTEXT — This user is FIELD STAFF / SUPPORT WORKER:
- staffType: {staff_type}, organizationId: {org_id}
- For "my shifts" / personal data: use /mobile/staff-shift/* or /mobile/organization-member/* endpoints
- DO NOT use /organization/* admin endpoints (will return 401/403)
- DO NOT use /super-admin/* (platform-scoped)
"""

    # Include recent conversation to resolve entity references like "Client Aryan",
    # "that shift", "him/her" — find_best_api needs to know what was returned previously
    # so it can extract entity IDs (clientId, shiftId, etc.) from the last assistant response.
    recent_context = ""
    if conversation_history:
        snippets = []
        for turn in conversation_history[-4:]:
            role = turn.get("role", "").upper()
            for part in turn.get("content", []) or []:
                if isinstance(part, dict) and part.get("text"):
                    text = part["text"]
                    if len(text) > 1500:
                        text = text[:1500] + "…"
                    snippets.append(f"{role}: {text}")
        if snippets:
            recent_context = "\n\nRecent conversation (use to resolve entity references like client names → IDs):\n" + "\n".join(snippets)

    # Compute today in Australia/Sydney (for "today" / "this week" reasoning) AND
    # convert to UTC ISO (with Z) for the actual API params — the backend expects UTC.
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    aus_tz = ZoneInfo("Australia/Sydney")
    now_aus = datetime.now(aus_tz)
    today_str = now_aus.strftime("%A, %d %B %Y")
    aus_offset_str = now_aus.strftime("%z")
    aus_offset_human = aus_offset_str[:3] + ":" + aus_offset_str[3:]  # +1100 → +11:00

    # Examples: today's start/end in UTC Z format (so the LLM can mimic this exact pattern)
    today_start_aus = now_aus.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_aus = now_aus.replace(hour=23, minute=59, second=59, microsecond=999000)
    today_start_utc = today_start_aus.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    today_end_utc = today_end_aus.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    system_prompt = f"""
    Route API calls. User type: {user_type}, Roles: {user_context['roles']}, Org ID: {org_id}.

    TODAY IS (Australia/Sydney): {today_str}, timezone offset {aus_offset_human}
    TODAY in UTC ISO (example values for the API):
    from = {today_start_utc}
    to   = {today_end_utc}

    {context_notes}
    {get_api_description()}
    {recent_context}

    Respond ONLY with JSON:
    {{"api_path": "<path>", "method": "<GET|POST|PUT|DELETE>", "parameters": {{}}, "query_params": {{}}, "reasoning": "<why>"}}

    ENTITY RESOLUTION:
    If the user references an entity by name (e.g. "Client Aryan", "that shift") and the recent conversation contains the matching ID, use that ID in `parameters`. If the ID is not visible in the conversation, pick a search/list endpoint with the name as a filter parameter instead.

    SHIFT LIST-VIEW ENDPOINT RULES (/organization/shift/list-view/type, /organization-member/shift/list-view, /isw/shift/list-view and similar):
    - `type` is REQUIRED. Pick ONE of: "draft", "scheduled", "thisweek", "completed".
    - "thisweek" → shifts within the current week (Mon-Sun). NO from/to needed.
    - "scheduled" → upcoming shifts EXCLUDING this week. REQUIRES from/to.
    - "completed" → past completed shifts. REQUIRES from/to.
    - "draft" → unfinalised shifts. from/to optional.
    - `from` and `to` MUST be UTC ISO with the literal "Z" suffix — example: "2026-05-01T00:00:00.000Z"
    - NEVER use Australian timezone offset (+10:00 / +11:00) in the API params. Reason in Australian time but ALWAYS emit UTC Z values.
    - The user is in Australia — when they say "today" or "this week", that means today/this week in AUSTRALIAN local time. Compute the date boundaries in Australian time, THEN convert to UTC Z.

    TYPE-PICKING EXAMPLES (no date) — for shift queries:
    - "my shifts", "what shifts do i have", "shifts" → type="thisweek" (default to current week)
    - "upcoming shifts", "shifts next week", "future shifts" → type="scheduled" + from=tomorrow 00:00 AUS in UTC, to=+30 days in UTC
    - "completed shifts", "past shifts", "shifts last week" → type="completed" + from/to covering that range in UTC
    - "draft shifts" → type="draft"

    DATE EXAMPLES (today is {today_str}):
    - "today" → from = {today_start_utc}, to = {today_end_utc}
    - "tomorrow" → from = (today+1 in AUS, then UTC Z), to = (today+1 23:59 AUS, then UTC Z)
    - "last week" → from = (last Monday 00:00 AUS in UTC Z), to = (last Sunday 23:59 AUS in UTC Z)
    - "this week" → use type="thisweek", skip from/to
    - "on 11 May" → from = (11 May 00:00 AUS in UTC Z), to = (11 May 23:59 AUS in UTC Z)

    ALL OTHER DATE-BASED ENDPOINTS (payroll, allowances, calendar-view, etc.):
    - Use the SAME UTC Z format for any date param.
    - Default to "this week" if user didn't specify a date and the endpoint requires dates."""

    messages = [{"role": "user", "content": [{"text": user_question}]}]
    # Internal API selector — output is JSON, not user-facing, skip guardrails
    response = call_bedrock(messages, system_prompt, use_guardrail=False)

    if not response:
        return None

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            decision = json.loads(json_match.group())
            # Debug visibility: show full API decision incl. date params
            import sys as _sys
            try:
                from config import VERBOSE as _VERBOSE
                if _VERBOSE:
                    print(f"[find_best_api] picked: {decision.get('api_path')} method={decision.get('method')}", file=_sys.stderr)
                    if decision.get("query_params"):
                        print(f"[find_best_api] query_params: {decision['query_params']}", file=_sys.stderr)
                    if decision.get("parameters"):
                        print(f"[find_best_api] parameters: {decision['parameters']}", file=_sys.stderr)
            except Exception:
                pass
            return decision
    except:
        pass

    return None


def construct_api_url(api_path, path_params):
    """Replace path parameters with values"""
    url = api_path
    for param_name, param_value in path_params.items():
        url = url.replace(f"{{{param_name}}}", str(param_value))
    # Avoid urljoin (it strips /api from base URL when path starts with /)
    if not url.startswith("/"):
        url = "/" + url
    return f"{API_BASE_URL}{url}"


# Generic GET response cache — first call hits the API, subsequent calls within
# TTL reuse the response. Bypassed when caller passes use_cache=False (e.g. user
# explicitly asked for "refresh"/"latest"). Keyed by (url, query_params).
import time as _time
_API_CACHE_TTL_SECONDS = 600  # 10 minutes
_api_cache = {}  # cache_key → (timestamp, response)


def _make_cache_key(url, query_params):
    qp = json.dumps(query_params or {}, sort_keys=True)
    return f"{url}|{qp}"


# Terminal-direct stream — bypasses any redirect_stderr() context (e.g. the one
# Streamlit's ui.py uses to capture model output). Every HTTP call to the
# backend is logged here so the launching terminal always shows what the agent
# is doing in real time. Imported once; used unconditionally.
import sys as _sys
_TERMINAL = _sys.__stderr__


def _short_url(url):
    """Strip the base URL for terminal readability."""
    try:
        from config import API_BASE_URL as _base
        if url.startswith(_base):
            return url[len(_base):]
    except Exception:
        pass
    return url


def _fmt_qp(qp):
    if not qp:
        return ""
    pairs = "&".join(f"{k}={v}" for k, v in qp.items())
    if len(pairs) > 120:
        pairs = pairs[:120] + "…"
    return f"?{pairs}"


def _shape_preview(result, max_chars=200):
    """One-line preview of an API response — top-level keys, list counts,
    'total' fields if present. Helps quickly see if a 200 OK is genuinely
    empty or has data we're failing to surface elsewhere."""
    try:
        if isinstance(result, list):
            return f"list[{len(result)}]"
        if not isinstance(result, dict):
            return f"{type(result).__name__}"
        # Walk one layer deeper into envelopes to find the real records list
        keys = list(result.keys())
        bits = [f"keys={keys[:6]}"]
        # Look for the actual records list at common nesting paths
        data = result.get("data")
        if isinstance(data, list):
            bits.append(f"data=list[{len(data)}]")
        elif isinstance(data, dict):
            inner_keys = list(data.keys())[:6]
            bits.append(f"data.keys={inner_keys}")
            for k in ("shifts", "items", "rows", "list", "records", "clients", "staff"):
                if isinstance(data.get(k), list):
                    bits.append(f"data.{k}=list[{len(data[k])}]")
                    break
            t = data.get("total") or data.get("totalCount") or data.get("totalRecords")
            if isinstance(t, (int, float)):
                bits.append(f"data.total={int(t)}")
        # Top-level total
        t = result.get("total") or result.get("totalCount") or result.get("totalRecords")
        if isinstance(t, (int, float)):
            bits.append(f"total={int(t)}")
        out = " ".join(bits)
        return out[:max_chars] + ("…" if len(out) > max_chars else "")
    except Exception as e:
        return f"<preview-err: {type(e).__name__}>"


# Rolling response dump — /tmp/sena_api_log.jsonl. One JSON line per call.
# Lets you tail or inspect the FULL body for any call when terminal preview
# isn't enough. Trimmed to keep the file from growing forever.
import os as _os
_API_DUMP_PATH = "/tmp/sena_api_log.jsonl"
_API_DUMP_MAX_BYTES = 5 * 1024 * 1024  # 5 MB rolling cap


def _dump_response(short_path, method, query_params, result, status, elapsed_ms, size):
    """Append the full response to /tmp/sena_api_log.jsonl for inspection.
    Best-effort — never raises."""
    try:
        # If the file is too big, truncate it (rolling)
        if _os.path.exists(_API_DUMP_PATH) and _os.path.getsize(_API_DUMP_PATH) > _API_DUMP_MAX_BYTES:
            with open(_API_DUMP_PATH, "w") as fh:
                fh.write("")  # truncate
        entry = {
            "ts": _time.time(),
            "method": method,
            "path": short_path,
            "query": query_params or {},
            "status": status,
            "elapsed_ms": elapsed_ms,
            "size_bytes": size,
            "body": result,
        }
        with open(_API_DUMP_PATH, "a") as fh:
            fh.write(json.dumps(entry, default=str)[:200000])  # cap one entry at 200 KB
            fh.write("\n")
    except Exception:
        pass  # diagnostic only — never fail the call


def call_target_api(method, url, query_params=None, body_params=None, use_cache=True):
    """Call the target API. GET responses are cached (10 min) by default.

    Pass use_cache=False to force a fresh fetch (e.g. user said "refresh"/"latest").
    Mutating methods (POST/PUT/DELETE) are never cached.

    Every call is logged to the original terminal stderr (sys.__stderr__) so the
    Streamlit-launching shell sees a live trace of the agent's HTTP activity,
    even when ui.py redirects stderr to capture model output.
    """
    short_path = _short_url(url) + _fmt_qp(query_params)
    method_u = method.upper()

    if not has_auth_token():
        print(f"[API] ✗ NOAUTH    {method_u} {short_path}", file=_TERMINAL, flush=True)
        return {
            "error": "Backend session context is not loaded",
            "status_code": 401,
            "auth_context_missing": True,
        }

    # Check cache for GET requests
    if use_cache and method_u == 'GET':
        cache_key = _make_cache_key(url, query_params)
        cached = _api_cache.get(cache_key)
        if cached and (_time.time() - cached[0]) < _API_CACHE_TTL_SECONDS:
            print(f"[API] cache HIT  {method_u} {short_path}", file=_TERMINAL, flush=True)
            return cached[1]

    print(f"[API] →         {method_u} {short_path}", file=_TERMINAL, flush=True)
    _t0 = _time.time()

    try:
        headers = get_auth_headers()

        if method_u == 'GET':
            response = requests.get(url, params=query_params, headers=headers, timeout=10)
        elif method_u == 'POST':
            response = requests.post(url, json=body_params, params=query_params, headers=headers, timeout=10)
        elif method_u == 'PUT':
            response = requests.put(url, json=body_params, params=query_params, headers=headers, timeout=10)
        elif method_u == 'DELETE':
            response = requests.delete(url, params=query_params, headers=headers, timeout=10)
        else:
            print(f"[API] ✗ unsupported method {method_u}", file=_TERMINAL, flush=True)
            return {"error": f"Unsupported HTTP method: {method}"}

        elapsed_ms = int((_time.time() - _t0) * 1000)

        if response.status_code in [200, 201]:
            try:
                result = response.json()
            except Exception:
                result = {"data": response.text}

            # Cache successful GET responses
            if method_u == 'GET':
                cache_key = _make_cache_key(url, query_params)
                _api_cache[cache_key] = (_time.time(), result)

            size = len(response.content) if hasattr(response, "content") else 0
            # Quick "what's actually in this response?" preview so we can
            # debug empty/sparse data without manually inspecting every API.
            preview = _shape_preview(result)
            print(
                f"[API] ←  {response.status_code} OK  {short_path}  ({elapsed_ms}ms, {size}B)  {preview}",
                file=_TERMINAL, flush=True,
            )
            # Dump full response to a rolling log file for deeper inspection.
            _dump_response(short_path, method_u, query_params, result, response.status_code, elapsed_ms, size)
            return result
        else:
            print(
                f"[API] ←  {response.status_code} ERR {short_path}  ({elapsed_ms}ms)  "
                f"body={response.text[:160]!r}",
                file=_TERMINAL, flush=True,
            )
            return {
                "error": f"API returned {response.status_code}",
                "status_code": response.status_code,
                "details": response.text[:300],
            }
    except requests.exceptions.Timeout:
        print(f"[API] ✗ TIMEOUT   {method_u} {short_path}", file=_TERMINAL, flush=True)
        return {"error": "API call timed out", "status_code": 0}
    except requests.exceptions.ConnectionError:
        print(f"[API] ✗ CONNERR   {method_u} {short_path}", file=_TERMINAL, flush=True)
        return {"error": f"Cannot reach {url}", "status_code": 0}
    except Exception as e:
        print(f"[API] ✗ EXC       {method_u} {short_path}  {type(e).__name__}: {e}", file=_TERMINAL, flush=True)
        return {"error": str(e), "status_code": 0}




def check_access(api_path):
    """Check if user role can access this API"""
    user_type = user_context.get("user_type", "unknown")

    restricted = {
        "admin": ["/organization/", "/sena-admin"],
        "staff": ["/mobile/staff-shift", "/mobile/organization-member", "/organization-member/shift"],
        "client": ["/mobile/client", "/mobile/client-shift"],
        "guardian": ["/mobile/visitor"]
    }

    allowed_paths = restricted.get(user_type, [])

    if user_type == "admin":
        return True

    for path in allowed_paths:
        if path in api_path:
            return True

    return False
