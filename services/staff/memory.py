"""Memory backends: AgentCore short-term events, DynamoDB raw audit, in-memory history.

Also contains the memory-first gate (`_try_answer_from_memory`) and verification
detection (`_skip_memory_gate`) used by the top-level router.
"""
import json
import re
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import (
    AGENTCORE_MEMORY_ID,
    AGENTCORE_SESSION_TTL_HOURS,
    bedrock_agentcore,
    chat_audit_table,
    CHAT_AUDIT_TTL_DAYS,
    SESSION_RECENT_TURNS,
    SESSION_ROW_TTL_DAYS,
    SESSION_TABLE_NAME,
    session_table,
    VERBOSE,
)
from state import user_context, conversation_history
from guardrails import _scrub_for_persistence
from bedrock_client import call_bedrock
from style_guide import AUSTRALIAN_ENGLISH_MEMORY


_SESSION_REGISTRY_PATH = Path(__file__).with_name(".memory_sessions.json")
_AUSTRALIA_TZ = ZoneInfo("Australia/Sydney")

# AgentCore sessionId / actorId constraint: must start with alphanumeric, then only [a-zA-Z0-9-_]
_AGENTCORE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]*$")


def _actor_id():
    """Composite tenant_user identifier for AgentCore — strict isolation per (org, user).

    Note: AgentCore actorId only allows [a-zA-Z0-9][a-zA-Z0-9-_/]*(:...)? so we use
    '_' as the separator between org and user, not '#'.
    """
    org = user_context.get("organization_id") or "no-org"
    uid = user_context.get("user_id") or "anon"
    return f"{org}_{uid}"


# ---- USER_PREFERENCE retrieval (AgentCore long-term memory) ----
# Process-local cache so repeat turns within a session don't re-hit AgentCore.
# Latency on a cache miss is ~200ms — well below the parallel Bedrock budget.
_PREFS_CACHE_TTL_SECONDS = 300
_prefs_cache = {}  # actor_id → (timestamp, list[str])


def _fetch_user_preferences(actor_id):
    """Return a list of preference strings for this actor (cached 5 min).

    Failures are non-fatal — chat is never blocked by AgentCore being unavailable
    or slow. We just log to stderr and return an empty list (which means "no
    personalisation this turn").
    """
    if not AGENTCORE_MEMORY_ID or not bedrock_agentcore:
        return []

    cached = _prefs_cache.get(actor_id)
    if cached and (time.time() - cached[0]) < _PREFS_CACHE_TTL_SECONDS:
        return cached[1]

    namespace = f"/users/{actor_id}/preferences/"
    try:
        resp = bedrock_agentcore.retrieve_memory_records(
            memoryId=AGENTCORE_MEMORY_ID,
            namespace=namespace,
            searchCriteria={
                "searchQuery": "user preferences and communication style",
                "topK": 3,
            },
        )
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            print(f"[memory] preferences namespace not yet populated for {actor_id} "
                  f"(extraction is async — needs a few turns)", file=sys.stderr)
        else:
            print(f"[memory] retrieve_memory_records (preferences) failed: {e}", file=sys.stderr)
        _prefs_cache[actor_id] = (time.time(), [])
        return []

    # Response shape: {"memoryRecordSummaries": [{"content": {"text": "..."}}, ...]}
    # We defensively walk a few field shapes since the SDK has shifted in 2026.
    prefs = []
    for record in (resp.get("memoryRecordSummaries") or resp.get("memoryRecords") or []):
        content = record.get("content") or {}
        text = content.get("text") if isinstance(content, dict) else content
        if not text:
            text = record.get("text") or record.get("summary") or ""
        if text:
            prefs.append(text.strip())

    if VERBOSE:
        print(f"[memory] fetched {len(prefs)} preferences for {actor_id}", file=sys.stderr)
    _prefs_cache[actor_id] = (time.time(), prefs)
    return prefs


_summaries_cache = {}  # actor_id → (timestamp, list[str])


def _fetch_session_summaries(actor_id, k=3):
    """Return up to k summaries of prior sessions for this actor (cached 5 min).

    The SUMMARY strategy in deploy_memory.py stores rolling summaries at
    `/summaries/{actorId}/{sessionId}/` — one per session. Querying the parent
    namespace surfaces the most relevant ones across all sessions, giving the
    bot cross-session awareness ("last time we talked about X").

    Empty list when the namespace is empty (early days for a user) or on any
    AgentCore failure — chat is never blocked.
    """
    if not AGENTCORE_MEMORY_ID or not bedrock_agentcore:
        return []

    cached = _summaries_cache.get(actor_id)
    if cached and (time.time() - cached[0]) < _PREFS_CACHE_TTL_SECONDS:
        return cached[1]

    namespace = f"/summaries/{actor_id}/"
    try:
        resp = bedrock_agentcore.retrieve_memory_records(
            memoryId=AGENTCORE_MEMORY_ID,
            namespace=namespace,
            searchCriteria={
                "searchQuery": "previous conversation summary topics discussed",
                "topK": k,
            },
        )
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            print(f"[memory] no session summaries yet for {actor_id} "
                  f"(SUMMARY extraction runs after a session has enough content)",
                  file=sys.stderr)
        else:
            print(f"[memory] retrieve_memory_records (summaries) failed: {e}", file=sys.stderr)
        _summaries_cache[actor_id] = (time.time(), [])
        return []

    summaries = []
    for record in (resp.get("memoryRecordSummaries") or resp.get("memoryRecords") or []):
        content = record.get("content") or {}
        text = content.get("text") if isinstance(content, dict) else content
        if not text:
            text = record.get("text") or record.get("summary") or ""
        if text:
            summaries.append(text.strip())

    if VERBOSE:
        print(f"[memory] fetched {len(summaries)} prior-session summaries for {actor_id}",
              file=sys.stderr)
    _summaries_cache[actor_id] = (time.time(), summaries)
    return summaries


# ---- User timezone persistence (30-day cache) ----
# Stored in AgentCore preferences namespace + DDB chat_audit (audit trail).
# When user volunteers their timezone via chat ("I'm in Perth"), we save it.
# On next login, we load it; expired (>30d) entries are treated as missing,
# triggering a re-ask.
_TIMEZONE_TTL_DAYS = 30


def _save_user_timezone(tz_iana: str):
    """Persist the user's IANA timezone to both AgentCore (long-term memory)
    and DDB chat_audit (audit trail). Sets user_context["timezone"] in-process.

    Failures are non-fatal — in-process value still updates so the current
    session benefits even if persistence breaks.
    """
    actor_id = _actor_id()
    now = datetime.now(timezone.utc)
    iso = now.isoformat()

    # 1) Update in-process state immediately
    user_context["timezone"] = tz_iana

    # 2) AgentCore — write as a USER preference event so it gets extracted
    #    into the /users/{actor_id}/preferences/ namespace by the USER_PREFERENCE
    #    strategy and surfaces on future logins.
    if AGENTCORE_MEMORY_ID and bedrock_agentcore:
        try:
            pref_text = (
                f"The user's timezone is {tz_iana}. They told us this on {iso}. "
                f"Use this timezone for all date/time calculations like 'today', "
                f"'this week', month names. If more than 30 days old since this "
                f"date, treat as stale and re-ask."
            )
            bedrock_agentcore.create_event(
                memoryId=AGENTCORE_MEMORY_ID,
                actorId=actor_id,
                sessionId=_session_id(),
                eventTimestamp=now,
                payload=[
                    {"conversational": {"role": "USER", "content": {"text": f"My timezone is {tz_iana}."}}},
                    {"conversational": {"role": "ASSISTANT", "content": {"text": pref_text}}},
                ],
                clientToken=str(uuid.uuid4()),
            )
            if VERBOSE:
                print(f"[memory] timezone saved to AgentCore: {tz_iana}", file=sys.stderr)
        except Exception as e:
            print(f"[memory] AgentCore timezone save failed: {e}", file=sys.stderr)

    # 3) DDB chat_audit — explicit timezone preference row (separate from per-turn rows)
    if chat_audit_table:
        try:
            expires_at = int((now + timedelta(days=_TIMEZONE_TTL_DAYS)).timestamp())
            chat_audit_table.put_item(Item={
                "pk": actor_id,
                "sk": f"timezone#{iso}",
                "kind": "user_timezone",
                "timezone": tz_iana,
                "set_at": iso,
                "expires_at": expires_at,
            })
            if VERBOSE:
                print(f"[memory] timezone saved to DDB (expires {expires_at})", file=sys.stderr)
        except Exception as e:
            print(f"[memory] DDB timezone save failed: {e}", file=sys.stderr)


# Process-local cache to avoid hitting AgentCore/DDB on every turn
_tz_cache = {}  # actor_id → (loaded_at_epoch, tz_iana_or_None)
_TZ_CACHE_TTL_SECONDS = 600  # 10 min in-process; storage is source of truth


def _load_user_timezone() -> str | None:
    """Load the user's timezone from persistent storage. Returns the IANA name
    if found and < 30 days old, else None (caller should fall back to Sydney
    and prompt the user to set their timezone).

    Reads from DDB chat_audit first (has explicit set_at + expires_at metadata),
    falls back to AgentCore preferences scan.
    """
    actor_id = _actor_id()

    cached = _tz_cache.get(actor_id)
    if cached and (time.time() - cached[0]) < _TZ_CACHE_TTL_SECONDS:
        return cached[1]

    tz_iana = None
    now_ts = datetime.now(timezone.utc).timestamp()

    # 1) DDB lookup — most recent timezone#... row
    if chat_audit_table:
        try:
            resp = chat_audit_table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={":pk": actor_id, ":prefix": "timezone#"},
                ScanIndexForward=False,  # newest first
                Limit=1,
            )
            items = resp.get("Items") or []
            if items:
                latest = items[0]
                expires_at = int(latest.get("expires_at", 0))
                if expires_at > now_ts:
                    tz_iana = latest.get("timezone")
                    if VERBOSE:
                        print(f"[memory] loaded timezone from DDB: {tz_iana}", file=sys.stderr)
                else:
                    if VERBOSE:
                        print(f"[memory] timezone in DDB but expired ({expires_at} < now)", file=sys.stderr)
        except Exception as e:
            print(f"[memory] DDB timezone load failed: {e}", file=sys.stderr)

    # 2) AgentCore preferences fallback — scan for "timezone" mentions
    if not tz_iana and AGENTCORE_MEMORY_ID and bedrock_agentcore:
        try:
            resp = bedrock_agentcore.retrieve_memory_records(
                memoryId=AGENTCORE_MEMORY_ID,
                namespace=f"/users/{actor_id}/preferences/",
                searchCriteria={"searchQuery": "user timezone IANA location state", "topK": 3},
            )
            for record in (resp.get("memoryRecordSummaries") or resp.get("memoryRecords") or []):
                content = record.get("content") or {}
                text = (content.get("text") if isinstance(content, dict) else content) or ""
                # Look for the IANA pattern we wrote in _save_user_timezone
                match = re.search(r"timezone is (Australia/[A-Za-z_]+)", text)
                if match:
                    tz_iana = match.group(1)
                    if VERBOSE:
                        print(f"[memory] loaded timezone from AgentCore: {tz_iana}", file=sys.stderr)
                    break
        except Exception as e:
            if VERBOSE:
                print(f"[memory] AgentCore timezone load failed (non-fatal): {e}", file=sys.stderr)

    _tz_cache[actor_id] = (time.time(), tz_iana)
    return tz_iana


def _format_user_profile():
    """Build the per-user system-prompt tier — role/org/preferences/summaries.

    Returned string is injected after the global stable system prompt with a
    cachePoint between them, so it caches per-user (not per-turn) on Bedrock.
    Returns an empty string when there's nothing personal to add.
    """
    if not user_context.get("authenticated"):
        return ""

    actor_id = _actor_id()
    prefs = _fetch_user_preferences(actor_id)
    summaries = _fetch_session_summaries(actor_id)

    lines = ["## About this user (you can answer profile questions like 'what is my role' DIRECTLY from this — no API call needed)"]
    user_type = user_context.get("user_type") or "unknown"
    roles = user_context.get("roles") or []
    org = user_context.get("organization_id") or "—"
    email = user_context.get("email") or "—"
    staff_type = user_context.get("staff_type") or ""
    lines.append(f"- Email: {email}")
    lines.append(f"- Role / user type: {user_type}")
    if staff_type:
        lines.append(f"- Staff type: {staff_type}")
    if roles:
        lines.append(f"- Granted roles: {', '.join(roles)}")
    lines.append(f"- Organisation ID: {org}")
    lines.append("")
    lines.append("If the user asks 'what is my role', 'who am I', 'what are my permissions', 'my profile', etc. — answer from the fields above immediately. Do NOT trigger an API call.")

    if prefs:
        lines.append("")
        lines.append("## What you remember about them")
        lines.append("(Use these to match their preferred style. Never quote them back literally.)")
        for p in prefs:
            lines.append(f"- {p}")

    if summaries:
        lines.append("")
        lines.append("## What you've discussed with them before")
        lines.append("(These are summaries of past sessions. Reference them naturally when relevant "
                     "— e.g. 'last time you asked about X'. Don't volunteer them out of context.)")
        for s in summaries:
            lines.append(f"- {s}")

    return "\n".join(lines)


def _session_id():
    """Return a per-actor AgentCore session id that stays stable for 24 hours.

    Storage: DynamoDB (`SENA_AI_SESSION_TABLE`) when configured, else local
    `.memory_sessions.json`. The row inside the chosen backend lives 90 days
    (DDB native TTL) while the session_id itself rotates every 24h — short-
    term continuity + long-term cleanup.

    All backend failures fall through silently to a fresh in-memory session_id
    for this turn so chat is never blocked by storage hiccups; the failure
    reason is logged to stderr.
    """
    actor_id = _actor_id()
    now = datetime.now(_AUSTRALIA_TZ)
    session = _read_session(actor_id) or {}

    expires_at = _parse_memory_timestamp(session.get("expires_at"))
    cached_id = session.get("session_id")
    if cached_id and expires_at and now < expires_at and _AGENTCORE_ID_RE.match(cached_id):
        return cached_id
    if cached_id and not _AGENTCORE_ID_RE.match(cached_id):
        print(f"[memory] session row for actor={actor_id} failed validation — regenerating",
              file=sys.stderr)

    uid = user_context.get("user_id") or "anon"
    expiry = now + timedelta(hours=AGENTCORE_SESSION_TTL_HOURS)
    new_session = {
        "session_id": f"sess-{now.strftime('%Y%m%dT%H%M%S')}-{uid}-{uuid.uuid4().hex[:8]}",
        "created_at": now.isoformat(),
        "expires_at": expiry.isoformat(),
    }
    _write_session(actor_id, new_session, now)
    return new_session["session_id"]


# ---- Session backend: DynamoDB preferred, local JSON fallback ----

def _read_session(actor_id):
    """Fetch the session row for an actor. Returns dict or None."""
    if session_table is not None:
        try:
            resp = session_table.get_item(Key={"actor_id": actor_id})
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if code == "ResourceNotFoundException":
                print(f"[memory] session table '{SESSION_TABLE_NAME}' not found — "
                      f"run deploy_dynamodb.py", file=sys.stderr)
            elif code == "AccessDeniedException":
                print(f"[memory] DDB GetItem AccessDenied on '{SESSION_TABLE_NAME}' — "
                      f"IAM policy needs dynamodb:GetItem", file=sys.stderr)
            elif code in ("ProvisionedThroughputExceededException", "ThrottlingException"):
                print(f"[memory] DDB throttled on GetItem — using in-memory session for this turn",
                      file=sys.stderr)
                return None
            else:
                print(f"[memory] DDB GetItem failed: {e} — falling back to local session file",
                      file=sys.stderr)
            return _read_session_local(actor_id)

        item = resp.get("Item")
        if not item:
            return None  # expected on first turn for a new actor — silent
        # Strip DDB-only attributes; caller only cares about session_id / created_at / expires_at.
        return {k: item.get(k) for k in ("session_id", "created_at", "expires_at")}

    return _read_session_local(actor_id)


def _write_session(actor_id, session, now):
    """Persist a session row. Failure is logged but never raised."""
    if session_table is not None:
        try:
            expiry = _parse_memory_timestamp(session.get("expires_at"))
            ttl_epoch = int((now + timedelta(days=SESSION_ROW_TTL_DAYS)).timestamp())
            session_table.put_item(Item={
                "actor_id":   actor_id,
                "session_id": session["session_id"],
                "created_at": session["created_at"],
                "expires_at": session["expires_at"],
                "ttl":        ttl_epoch,
            })
            return
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if code == "AccessDeniedException":
                print(f"[memory] DDB PutItem AccessDenied — IAM policy needs dynamodb:PutItem",
                      file=sys.stderr)
            else:
                print(f"[memory] DDB PutItem failed: {e} — session_id not persisted",
                      file=sys.stderr)
            # Continue with this turn's fresh id; next turn re-tries.
            return

    _write_session_local(actor_id, session, now)


def _read_session_local(actor_id):
    """Local-file fallback: read one actor's session row."""
    try:
        if not _SESSION_REGISTRY_PATH.is_file():
            return None
        with _SESSION_REGISTRY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data.get(actor_id) or None
    except Exception as e:
        print(f"[memory] local session file read failed: {e}", file=sys.stderr)
        return None


def _write_session_local(actor_id, session, now):
    """Local-file fallback: upsert one actor's session row, prune expired."""
    try:
        registry = {}
        if _SESSION_REGISTRY_PATH.is_file():
            try:
                with _SESSION_REGISTRY_PATH.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    registry = loaded
            except Exception:
                registry = {}

        registry[actor_id] = session

        # Prune rows past their session_id expiry (cheap incremental cleanup).
        active = {}
        for aid, s in registry.items():
            exp = _parse_memory_timestamp((s or {}).get("expires_at"))
            if exp and now < exp:
                active[aid] = s

        with _SESSION_REGISTRY_PATH.open("w", encoding="utf-8") as f:
            json.dump(active, f, indent=2, sort_keys=True)
    except Exception as e:
        print(f"[memory] local session file write failed: {e}", file=sys.stderr)


def _parse_memory_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _assemble_context(user_question):
    """Build the messages list to send to Bedrock.

    Combines AgentCore short-term events (last N session turns) with the
    current question. Falls back to the in-memory conversation_history if
    AgentCore is disabled.
    """
    messages = []

    if AGENTCORE_MEMORY_ID and bedrock_agentcore:
        try:
            resp = bedrock_agentcore.list_events(
                memoryId=AGENTCORE_MEMORY_ID,
                actorId=_actor_id(),
                sessionId=_session_id(),
                maxResults=SESSION_RECENT_TURNS,
            )
            for ev in resp.get("events", []):
                for blob in ev.get("payload", []) or []:
                    conv = blob.get("conversational") or {}
                    role = conv.get("role", "").lower()
                    text = (conv.get("content") or {}).get("text") or ""
                    if role in {"user", "assistant"} and text:
                        messages.append({"role": role, "content": [{"text": text}]})
        except Exception as e:
            print(f"[memory] AgentCore list_events failed: {e} — falling back to in-memory", file=sys.stderr)
            messages = list(conversation_history)
    else:
        messages = list(conversation_history)

    messages.append({"role": "user", "content": [{"text": user_question}]})
    return messages


def _persist_turn(user_question, assistant_text, mode, api_path=None, api_response=None):
    """Single write site for all memory backends.

    1. Scrubs assistant response via Guardrails (never store unredacted PII).
    2. Appends to in-memory conversation_history (process lifetime).
    3. Writes the turn to AgentCore Memory as conversational events (24h short-term
       + auto-extracted long-term via configured strategies).
    4. Writes raw API JSON to DynamoDB with 30d TTL (audit + spillover) — only
       for API-mode turns where api_response is present.
    """
    if not assistant_text:
        return

    clean_user = _scrub_for_persistence(user_question) or user_question
    clean_assistant = _scrub_for_persistence(assistant_text) or assistant_text

    # 1) In-memory (fallback + same-process recall)
    conversation_history.append({"role": "user", "content": [{"text": clean_user}]})
    conversation_history.append({"role": "assistant", "content": [{"text": clean_assistant}]})

    turn_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # 2) AgentCore Memory event (short-term, with auto long-term extraction)
    if AGENTCORE_MEMORY_ID and bedrock_agentcore:
        try:
            params = {
                "memoryId": AGENTCORE_MEMORY_ID,
                "actorId": _actor_id(),
                "sessionId": _session_id(),
                "eventTimestamp": now,
                "payload": [
                    {"conversational": {"role": "USER", "content": {"text": clean_user}}},
                    {"conversational": {"role": "ASSISTANT", "content": {"text": clean_assistant}}},
                ],
                "clientToken": str(uuid.uuid4()),
            }
            resp = bedrock_agentcore.create_event(**params)
            event_id = (resp.get("event") or {}).get("eventId")
            if event_id and VERBOSE:
                print(f"[memory] AgentCore event written:")
        except Exception as e:
            print(f"[memory] AgentCore create_event failed: {e}", file=sys.stderr)

    # 3) DynamoDB raw audit (30d TTL, only for API mode)
    if chat_audit_table and mode == "API" and api_response is not None:
        try:
            expires_at = int((now + timedelta(days=CHAT_AUDIT_TTL_DAYS)).timestamp())
            chat_audit_table.put_item(Item={
                "pk": _actor_id(),
                "sk": f"{now.isoformat()}#{turn_id}",
                "turn_id": turn_id,
                "mode": mode,
                "api_path": api_path or "",
                "user_text": clean_user,
                "assistant_text": clean_assistant,
                "api_response_json": json.dumps(api_response)[:380_000],  # DDB 400KB item cap, leave headroom
                "expires_at": expires_at,
            })
        except Exception as e:
            print(f"[memory] DDB put_item failed: {e}", file=sys.stderr)


def _handle_memory_command(command):
    """User-facing /memory subcommands: show | clear."""
    parts = command.strip().split()
    sub = parts[1].lower() if len(parts) > 1 else "show"

    if sub == "show":
        print(f"\n[memory] actorId={_actor_id()}, sessionId={_session_id()}")
        print(f"  In-memory turns this process: {len(conversation_history)}")
        if AGENTCORE_MEMORY_ID and bedrock_agentcore:
            try:
                resp = bedrock_agentcore.list_events(
                    memoryId=AGENTCORE_MEMORY_ID,
                    actorId=_actor_id(),
                    sessionId=_session_id(),
                    maxResults=20,
                )
                events = resp.get("events", [])
                print(f"  AgentCore session events (last {len(events)}):")
                for ev in events:
                    for blob in ev.get("payload", []) or []:
                        conv = blob.get("conversational") or {}
                        role = conv.get("role", "?")
                        text = (conv.get("content") or {}).get("text", "")[:80]
                        print(f"    {role}: {text}")
            except Exception as e:
                print(f"  AgentCore list_events failed: {e}")
        if chat_audit_table:
            try:
                from boto3.dynamodb.conditions import Key
                resp = chat_audit_table.query(
                    KeyConditionExpression=Key("pk").eq(_actor_id()),
                    ScanIndexForward=False,
                    Limit=20,
                )
                items = resp.get("Items", [])
                print(f"  DDB audit rows (last {len(items)}):")
                for it in items:
                    print(f"    {it.get('sk', '?')[:30]} mode={it.get('mode')} api={it.get('api_path', '-')}")
            except Exception as e:
                print(f"  DDB query failed: {e}")

    elif sub == "clear":
        conversation_history.clear()
        print("[memory] cleared in-memory conversation_history for this process")
        print("[memory] AgentCore + DDB are managed by their own TTLs and are NOT cleared by this command")

    else:
        print("[memory] usage: /memory [show|clear]")


def _try_answer_from_memory(user_question):
    """Always-on memory check: can we answer this from prior conversation alone?

    Runs BEFORE intent detection on every query. If recent conversation already
    contains the answer (regardless of phrasing or tense), returns the answer.
    If fresh data / a fresh action is required, returns None so the caller falls
    through to normal routing.

    Bypasses Bedrock Guardrails because the input is the user's own prior turns
    (already passed guardrails on the way in) and the model's job is bounded:
    answer-from-context or emit a sentinel.
    """
    if not conversation_history:
        return None  # nothing to recall from

    transcript_lines = []
    for turn in conversation_history[-12:]:
        role = turn.get("role", "").upper()
        for part in turn.get("content", []) or []:
            if isinstance(part, dict) and part.get("text"):
                transcript_lines.append(f"{role}: {part['text']}")
    if not transcript_lines:
        return None

    transcript = "\n".join(transcript_lines)

    system_prompt = f"""{AUSTRALIAN_ENGLISH_MEMORY} You are a memory-first gate for the SENA NDIS assistant. You see the conversation transcript and the user's current question.

Decide ONE thing: can the user's question be answered COMPLETELY and ACCURATELY from the transcript alone, without fetching anything?

Output rules (STRICT — no exceptions):
1. If the transcript fully covers the question → answer it naturally and DIRECTLY, as if it were the first time. Use only facts from the transcript. Australian English, warm, concise.
2. In ANY of these cases, reply with the single token `NEEDS_FRESH_DATA` and nothing else — no explanation, no apology, no "would you like me to…" offer:
   a. The transcript does not contain the answer.
   b. The transcript only PARTIALLY contains the answer (e.g. we have tomorrow's shifts and the user asks about "other days", "all days", "this week", or any scope beyond what's stored).
   c. The user uses fresh-data words: "refresh", "latest", "now", "current", "updated", "new", "fresh", "again — newer".
   d. The user is confirming or following up on an earlier offer to fetch ("yes", "sure", "go ahead", "do it", "all of them", "show me", "yes please") — never use memory to act on a confirmation; route through.
   e. The user is asking about a different entity, date range, or filter than what's already in the transcript.
3. Greetings, identity questions, generic conversational follow-ups that don't depend on data → answer naturally.

NEVER use meta-commentary about the conversation history. FORBIDDEN phrases (silent reuse, no exceptions):
- "I told you before"
- "as I mentioned"
- "as I said earlier"
- "I already listed"
- "I already showed you"
- "you asked this before"
- "we covered this"
- "above"
- "in our previous chat"
- "earlier I said"
- Any phrase referring to the prior turn's existence
Just answer the question directly using the facts. The user should not be able to tell whether the answer came from cache or a fresh fetch.

DO NOT:
- Half-answer ("I have X but for Y you'd need…"). Reply NEEDS_FRESH_DATA instead. Let the router fetch the full answer.
- Ask the user permission to fetch ("would you like me to…?"). Reply NEEDS_FRESH_DATA — the router will fetch automatically.
- Combine an answer with NEEDS_FRESH_DATA. It's one or the other, never both.

Default bias when uncertain: emit NEEDS_FRESH_DATA. A fresh fetch is always recoverable; a wrong half-answer wastes the user's next turn.

When you DO answer from memory: Australian English spelling (organisation, recognise, behaviour). Dates DD/MM/YYYY. No "mate" in compliance contexts. Never name the underlying model — if asked, "I'm the SENA NDIS assistant.\""""

    messages = [
        {
            "role": "user",
            "content": [{
                "text": (
                    f"Conversation transcript so far (oldest first):\n\n{transcript}\n\n"
                    f"User's current question: {user_question}\n\n"
                    "Answer from the transcript, or reply with the single token NEEDS_FRESH_DATA."
                )
            }],
        }
    ]

    # Memory-gate input is user's own prior turns (already guarded) — skip to save rate limit
    response = call_bedrock(messages, system_prompt, user_profile=_format_user_profile(), use_guardrail=False)
    if not response:
        return None

    if response.strip().upper().startswith("NEEDS_FRESH_DATA"):
        return None

    return response.strip()


def _skip_memory_gate(user_question):
    """Bypass memory and go straight to API fetch.

    Triggers in two cases:
    1. Verification words ("verify", "check", "missing", etc.) — user wants confirmation
    2. Live-data domains (clients, shifts, rosters, payroll, allowances) — data changes
       behind the scenes, cached answers are stale by definition. Always re-fetch.
    """
    verification_words = [
        "verify", "check", "validate", "cross.check", "cross check", "recheck", "re-check",
        "missing", "wrong", "incorrect", "inaccurate", "mismatch", "discrepancy",
        "double.check", "double check", "confirm", "confirmation",
        "accurate", "correct", "right", "match"
    ]
    # Live-data keywords — never cache these answers, always re-fetch from API.
    # Includes singular/plural and common abbreviations.
    live_data_words = [
        "client", "clients",
        "shift", "shifts",
        "roster", "rosters",
        "schedule", "schedules", "scheduling",
        "payroll", "payslip", "payslips",
        "allowance", "allowances",
        "staff", "support worker", "support workers",
        "guardian", "guardians",
    ]
    lower_q = user_question.lower()
    for word in verification_words + live_data_words:
        if word in lower_q:
            return True
    return False
