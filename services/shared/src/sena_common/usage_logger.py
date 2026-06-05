"""AI usage logging — single sink: MongoDB.

One function: `emit_usage(...)`. Every AI call site (voice onboarding turns,
case-note dictation, case-review classify/summarise) calls it with token
counters; the event is forwarded fire-and-forget to MongoDB
(`sena_common.mongo_usage_logger`) on a worker thread, landing in the per-user
`usage_logs` document (one doc per user, one entry per screen).

There is deliberately NO parallel logging path (no structlog event, no file
sink, no Postgres table) — MongoDB is the one source of truth for token usage.
Kill switch: SENA_AI_MONGO_USAGE_AUTOLOG=0.

Hard rules baked into the type signature:
  - NO prompt_text / response_text parameters — Gemini and Bedrock responses
    ARE prompts; logging them would breach NDIS APP 11. Counters and
    identifiers only.

Usage:
    from sena_common.usage_logger import emit_usage, UsageFeature
    emit_usage(
        tenant_id="tenant_abc",
        user_id="user_xyz",
        feature=UsageFeature.CASE_NOTE_SUMMARY,
        model="gemini-3-flash-preview",
        session_id="sess_123",
        prompt_tokens=5000,
        response_tokens=500,
    )
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import enum
import os
from typing import Any

import structlog

_log = structlog.get_logger("usage_logger")


class UsageFeature(str, enum.Enum):
    """Canonical AI feature IDs for the client credit model.

    All 8 features from the credit-model brief (2026-05-26). Slots #5 + #8
    are reserved for features not yet built; logger accepts them for forward
    compatibility once those services land.
    """

    VOICE_ONBOARDING = "voice_onboarding"
    CASE_NOTE_DRAFTING = "case_note_drafting"
    CASE_NOTE_SUMMARY = "case_note_summary"
    INCIDENT_REPORT_ANALYSIS = "incident_report_analysis"
    AI_CHAT = "ai_chat"  # reserved (#5 — feature not yet built)
    PSR_SUMMARY = "psr_summary"
    MONTHLY_REPORT = "monthly_report"
    STAFF_DOC_EXTRACTION = "staff_doc_extraction"  # reserved (#8 — feature not yet built)


# ── MongoDB forward ───────────────────────────────────────────────────────────
# pymongo blocks, and emit_usage fires inside async hot paths (voice turns), so
# the write runs fire-and-forget on a single worker thread — never on the
# caller's thread. The executor's atexit hook joins the worker on clean process
# exit, so final writes are not lost; a dead Mongo costs at most one connection
# timeout (the mongo module remembers the failure and no-ops afterwards).
_mongo_pool: concurrent.futures.ThreadPoolExecutor | None = None


def _mongo_autolog_args(record: dict[str, Any]) -> dict[str, Any]:
    """Map an AI-usage record to the Mongo `log_usage` contract. Pure.

    user       ← participant_id → user_id → session_id → tenant_id
    screenname ← step_id (voice onboarding screens) → feature (other services)
    """
    return {
        "user": str(
            record.get("participant_id")
            or record.get("user_id")
            or record.get("session_id")
            or record.get("tenant_id")
            or "unknown"
        ),
        "screenname": str(record.get("step_id") or record.get("feature") or "unknown"),
        "input_token": int(record.get("prompt_tokens") or 0),
        "output_token": int(record.get("response_tokens") or 0),
        "error": record.get("failure_reason"),
    }


def _forward_to_mongo(record: dict[str, Any]) -> None:
    """Fire-and-forget Mongo write on the worker thread. Never raises.

    Disabled with SENA_AI_MONGO_USAGE_AUTOLOG=0; no-ops harmlessly when no URI
    is configured (the mongo module handles that).
    """
    global _mongo_pool
    with contextlib.suppress(Exception):
        if os.environ.get("SENA_AI_MONGO_USAGE_AUTOLOG", "1") == "0":
            return
        from sena_common.mongo_usage_logger import log_usage

        args = _mongo_autolog_args(record)
        # Set SENA_AI_MONGO_USAGE_DEBUG=1 to watch the mapped fields stream live
        # in the server console during a test session (real token counts, not
        # the example data). Logs on the caller thread, before the async write.
        if os.environ.get("SENA_AI_MONGO_USAGE_DEBUG"):
            _log.info("mongo_usage_forward", **args)
        if _mongo_pool is None:
            _mongo_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="mongo-usage"
            )
        _mongo_pool.submit(log_usage, **args)


def emit_usage(
    *,
    tenant_id: str,
    user_id: str | None,
    feature: UsageFeature,
    model: str,
    session_id: str | None,
    prompt_tokens: int = 0,
    response_tokens: int = 0,
    cached_tokens: int = 0,
    prompt_audio_tokens: int = 0,
    response_audio_tokens: int = 0,
    audio_seconds_in: float = 0.0,
    audio_seconds_out: float = 0.0,
    tool_call_count: int = 0,
    latency_ms: int | None = None,
    success: bool = True,
    failure_reason: str | None = None,
    **extras: Any,
) -> None:
    """Record one AI usage event — forwarded to MongoDB. Never raises.

    Args:
        tenant_id: REQUIRED. Tenant/org owning this AI call. Authoritative source
            is the auth context (`assert_session_owner` / `AuthContext`).
            NEVER use a value from a request body.
        user_id: User (worker or client) who initiated the AI call. None when
            the call is system-triggered (e.g. nightly rollup).
        feature: Which of the 8 client-billable features. Use `UsageFeature`
            enum; never a free-string.
        model: Model id string (e.g. "gemini-3-flash-preview",
            "anthropic.claude-3-5-sonnet-20241022-v2:0", "gemini-3.1-flash-live-preview").
        session_id: Per-session identifier. Voice WS session_id, dictation
            shift_id, case-review request_id, etc.
        prompt_tokens: Input token count from the LLM response (`usage.input_tokens`
            for Bedrock, `usage_metadata.prompt_token_count` for Gemini).
        response_tokens: Output token count (`usage.output_tokens` /
            `usage_metadata.candidates_token_count`).
        cached_tokens: Gemini context-cache hit tokens. Accepted for forward
            compatibility; not stored in the Mongo schema yet.
        prompt_audio_tokens: AUDIO-modality subset of prompt_tokens (from
            usage_metadata.prompt_tokens_details). Accepted; not stored yet.
        response_audio_tokens: AUDIO-modality subset of response_tokens.
            Accepted; not stored yet.
        audio_seconds_in: Gemini Live user-audio seconds. Accepted; not stored yet.
        audio_seconds_out: Gemini Live TTS seconds. Accepted; not stored yet.
        tool_call_count: Function/tool calls this turn. Accepted; not stored yet.
        latency_ms: Round-trip latency in milliseconds.
        success: True on clean response; False on exception or non-200.
        failure_reason: Short enum-shaped reason (e.g. "timeout") — lands in the
            screen entry's `error` field.
        **extras: Per-feature non-PII fields. `step_id` becomes the Mongo
            `screenname`; `participant_id` becomes the Mongo `user` key.
            NEVER prompt text or participant data.
    """
    record: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "feature": feature.value if isinstance(feature, UsageFeature) else feature,
        "model": model,
        "session_id": session_id,
        "prompt_tokens": int(prompt_tokens or 0),
        "response_tokens": int(response_tokens or 0),
        "cached_tokens": int(cached_tokens or 0),
        "prompt_audio_tokens": int(prompt_audio_tokens or 0),
        "response_audio_tokens": int(response_audio_tokens or 0),
        "audio_seconds_in": float(audio_seconds_in or 0.0),
        "audio_seconds_out": float(audio_seconds_out or 0.0),
        "tool_call_count": int(tool_call_count or 0),
        "latency_ms": latency_ms,
        "success": bool(success),
        "failure_reason": failure_reason,
        **extras,
    }
    _forward_to_mongo(record)
