"""AI usage logger — MVP (Phase 1).

One function: `emit_usage(...)`. Writes a structlog JSON event named "ai_usage"
with normalised counter fields. No database, no CloudWatch direct write — just
structured logs. Downstream pipelines (CloudWatch agent on EC2, log forwarder,
or nightly aggregator) read the JSON.

Phase 2 (later, when we have 4 weeks of data and a stable schema) will graduate
to a Postgres `usage_events` table per the plan in
`.claude/plans/usage-logging/PLAN.md`. The field set here matches that future
schema 1-to-1 so the migration is a no-op for callers.

Hard rules baked into the type signature:
  - NO free-text fields beyond `tool_name` (enum-shaped, ≤80 chars).
  - NO prompt_text / response_text / field_value parameters — Gemini and
    Bedrock responses ARE prompts; logging them would breach NDIS APP 11.
  - Counters and identifiers only.

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
        latency_ms=420,
        success=True,
    )
"""

from __future__ import annotations

import enum
from typing import Any

import structlog

_log = structlog.get_logger("ai_usage")


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
    audio_seconds_in: float = 0.0,
    audio_seconds_out: float = 0.0,
    tool_call_count: int = 0,
    latency_ms: int | None = None,
    success: bool = True,
    failure_reason: str | None = None,
    **extras: Any,
) -> None:
    """Emit one AI usage event to structlog as a single JSON line.

    Never raises. Logger failures are swallowed — the AI critical path must
    never be blocked by telemetry.

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
            shift_id, case-review request_id, etc. Used to join per-turn rows
            (Phase 2) and forensic queries.
        prompt_tokens: Input token count from the LLM response (`usage.input_tokens`
            for Bedrock, `usage_metadata.prompt_token_count` for Gemini).
        response_tokens: Output token count (`usage.output_tokens` /
            `usage_metadata.candidates_token_count`).
        cached_tokens: Gemini context-cache hit tokens (free or discounted).
            0 for Bedrock or when no cache hit occurred.
        audio_seconds_in: For Gemini Live only — duration of user audio
            processed this turn/session. 0 for text-only models.
        audio_seconds_out: For Gemini Live only — duration of audio TTS
            produced. 0 for text-only models.
        tool_call_count: Number of function/tool calls Gemini made this
            turn/session. Useful for diagnosing tool-heavy patterns.
        latency_ms: Round-trip latency in milliseconds (client-side).
        success: True on clean response; False on exception or non-200.
        failure_reason: Short enum-shaped reason (e.g. "timeout",
            "rate_limited", "invalid_response"). Free-form NOT permitted.
        **extras: Per-feature non-PII fields (e.g. `note_count` for
            summariser, `step_id` for onboarding). NEVER prompt text or
            participant data.
    """
    try:
        _log.info(
            "ai_usage",
            tenant_id=tenant_id,
            user_id=user_id,
            feature=feature.value if isinstance(feature, UsageFeature) else feature,
            model=model,
            session_id=session_id,
            prompt_tokens=int(prompt_tokens or 0),
            response_tokens=int(response_tokens or 0),
            cached_tokens=int(cached_tokens or 0),
            audio_seconds_in=float(audio_seconds_in or 0.0),
            audio_seconds_out=float(audio_seconds_out or 0.0),
            tool_call_count=int(tool_call_count or 0),
            latency_ms=latency_ms,
            success=bool(success),
            failure_reason=failure_reason,
            **extras,
        )
    except Exception:
        # Telemetry must never break the AI critical path. Drop silently.
        # If structlog itself is broken there are bigger problems.
        pass
