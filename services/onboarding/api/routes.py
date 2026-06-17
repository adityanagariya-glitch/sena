from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from onboarding.api.deps import get_repo
from onboarding.core.settings import settings
from voice.form_state import FieldSource, FieldValue, FormState
from voice.schema_spec import StepSchema
from voice.session_bootstrap import SessionBootstrap
from voice.state_repo import FormStateRepo
from voice.webhook import fire_webhook
from onboarding.repositories.user_context_repo import UserContextRepo
from onboarding.services.cross_screen_context import build_summary

log = structlog.get_logger(__name__)


router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    participant_id: str
    step: str
    schema: StepSchema
    initial_state: dict | None = None
    # Rule 1 / Rule 2 hygiene contract. When provided, it is the authoritative
    # source for what state the agent inherits and which fields are read-only.
    # When omitted, a backwards-compatible bootstrap is synthesised from
    # initial_state (mode=returning_same_page if non-empty, else new_user).
    bootstrap: SessionBootstrap | None = None
    locale: str = "en-AU"
    tenant_id: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    ws_url: str
    expires_at: datetime
    resumption_handle: str | None = None


class UpdateStateRequest(BaseModel):
    values: dict


class ClientValidationErrorRequest(BaseModel):
    """Mobile-client-reported validation error (typed or voice input).

    Schema is strict (extra="forbid") so an unexpected field surfaces as a
    422 — matches the `unknown(false)` contract documented in the
    flutterhandoffdev.md handoff.
    """

    model_config = ConfigDict(extra="forbid")

    error_type: str = Field(..., min_length=1, max_length=64)
    error_message: str = Field(..., min_length=1, max_length=512)
    input_method: Literal["typed", "voice"]
    field_id: str = Field(..., min_length=1, max_length=128)
    attempted_value: Any | None = None
    ts: datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _step_id_to_number(step_id: str) -> int:
    """Map a step_id (e.g. "personal_information", "step3", "3") to an int.

    The cross-screen bucket keys summaries by step number for stable ordering
    and prompt rendering. This is a best-effort heuristic; unrecognised
    step_ids hash deterministically to a stable positive integer so two
    summaries for the same step_id always collide on the same hash field
    (the idempotency contract).
    """
    if step_id.isdigit():
        return int(step_id)
    # "step3" → 3
    digits = "".join(c for c in step_id if c.isdigit())
    if digits:
        try:
            return int(digits)
        except ValueError:
            pass
    # Stable, deterministic fallback. abs() keeps it positive.
    return abs(hash(step_id)) % 10_000


def _normalize_flat_to_nested(flat: dict) -> dict:
    """Convert flat dot-notation keys to nested dict.

    Flutter sends {"basics.full_name": "Mansi"} — normalised to
    {"basics": {"full_name": "Mansi"}} so the downstream loop can process it.
    Mixed inputs (some flat, some already nested dicts) are handled correctly.
    """
    nested: dict = {}
    for key, value in flat.items():
        if "." in key:
            section, _, field = key.partition(".")
            nested.setdefault(section, {})[field] = value
        else:
            existing = nested.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                existing.update(value)
            else:
                nested[key] = value
    return nested


def _build_initial_values(initial_state: dict | None) -> dict:
    """Wrap raw values dict from app into FieldValue format if not already wrapped."""
    if not initial_state:
        return {}

    # Flutter sends flat dot-notation {"section.field": value}; normalise first.
    if any("." in k for k in initial_state):
        initial_state = _normalize_flat_to_nested(initial_state)

    result = {}
    for section_id, section_data in initial_state.items():
        if isinstance(section_data, list):
            result[section_id] = [
                {
                    field_id: (
                        fv if isinstance(fv, dict) and "value" in fv
                        else FieldValue(value=fv, source=FieldSource.app).model_dump(mode="json")
                    )
                    for field_id, fv in row.items()
                }
                for row in section_data
                if isinstance(row, dict)
            ]
        elif isinstance(section_data, dict):
            # Flutter sends repeatable sections as flat key `section.rows: [...]`.
            # _normalize_flat_to_nested converts that to {"rows": [...]}.
            # Unwrap to a list so repeatable sections are stored correctly.
            rows_val = section_data.get("rows")
            if set(section_data.keys()) == {"rows"} and isinstance(rows_val, list):
                result[section_id] = [
                    {
                        field_id: (
                            fv if isinstance(fv, dict) and "value" in fv
                            else FieldValue(value=fv, source=FieldSource.app).model_dump(mode="json")
                        )
                        for field_id, fv in row.items()
                    }
                    for row in rows_val
                    if isinstance(row, dict)
                ]
            else:
                result[section_id] = {
                    field_id: (
                        fv if isinstance(fv, dict) and "value" in fv
                        else FieldValue(value=fv, source=FieldSource.app).model_dump(mode="json")
                    )
                    for field_id, fv in section_data.items()
                }

    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/v1/onboarding/session", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    req: CreateSessionRequest,
    request: Request,
    repo: FormStateRepo = Depends(get_repo),
) -> CreateSessionResponse:
    session_id = str(uuid.uuid4())
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.onboarding_session_max_min)

    # Resolve bootstrap envelope. Explicit takes precedence; legacy initial_state
    # is wrapped into a synthesised bootstrap so older clients keep working.
    bootstrap = req.bootstrap or SessionBootstrap.from_initial_state(req.initial_state)

    # TEMP DEBUG — dump raw client payload to diagnose per-screen state leak.
    # Remove after Flutter bootstrap shape confirmed correct.
    log.info(
        "debug_client_bootstrap_payload",
        session_id=session_id,
        participant_id=req.participant_id,
        has_explicit_bootstrap=req.bootstrap is not None,
        has_legacy_initial_state=req.initial_state is not None,
        bootstrap_mode=bootstrap.mode,
        current_page_values_keys=list(bootstrap.current_page_values.keys()),
        current_page_values_sample=dict(list(bootstrap.current_page_values.items())[:8]),
        readonly_paths=list(bootstrap.readonly_paths),
        prior_pages_keys=list(bootstrap.prior_pages.keys()) if bootstrap.prior_pages else [],
        participant_display_name=bootstrap.participant_display_name,
        legacy_initial_state_keys=list(req.initial_state.keys()) if req.initial_state else [],
    )

    # Auto-hydrate `bootstrap.prior_pages` from the cross-screen context bucket
    # when the client did not supply one. Client-supplied prior_pages always
    # wins (forward-compatibility, manual-override path during testing).
    if settings.onboarding_cross_screen_context_enabled and not req.tenant_id:
        log.warning(
            "session_create_tenant_id_missing",
            session_id=session_id,
            participant_id=req.participant_id,
            note="cross_screen_context flag is on but tenant_id is empty — "
                 "bucket lookup skipped, no shared context for this session",
        )
    if (
        settings.onboarding_cross_screen_context_enabled
        and not bootstrap.prior_pages
        and req.tenant_id
    ):
        ctx_repo = UserContextRepo(repo._r)
        bucket = await ctx_repo.get_bucket(req.tenant_id, req.participant_id)
        if not bucket.is_empty():
            # New CSC layer only forwards the 5-field allowlist (name, dob,
            # gender, goals, hobbies_interests). prior_pages now carries
            # concept-keyed dicts — see services/cross_screen_context.py.
            hydrated_prior = {
                f"step:{s.step_number}": {
                    **s.verbatim,
                    "_step_label": s.step_label,
                }
                for s in bucket.summaries
            }
            # Resolve participant_display_name. Priority order (highest → lowest):
            #   1. `current_page_values["basics.full_name"]` from THIS bootstrap
            #      — the live screen state mobile is showing right now. Always
            #      current because Flutter refreshes `ClientHomeController.
            #      client.value` after every voice session (refreshClientProfile).
            #   2. The bootstrap-supplied `participant_display_name`.
            #   3. Most-recent bucket summary that has a `name` (legacy fallback
            #      for sessions where mobile didn't send a name).
            #   4. Empty → greeting falls back to "Hi there".
            #
            # Regression context (2026-05-28): the bucket retained an old
            # "Aditya" summary from a session that completed BEFORE the
            # rename → Ethan got committed via update_field. With the previous
            # bucket-first ordering the prompt kept greeting "Hi Aditya" even
            # though mobile, FormState, and the API profile all agreed on
            # "Ethan Brown". The earlier (2026-05-20) Flutter-cache-stale
            # regression is now handled by the mobile-side refresh after
            # every session, so mobile is no longer a stale source.
            current_full_name: str | None = None
            cpv = bootstrap.current_page_values or {}
            raw_name = cpv.get("basics.full_name")
            current_full_name_full = ""
            if isinstance(raw_name, str) and raw_name.strip():
                current_full_name_full = raw_name.strip()
                current_full_name = current_full_name_full.split()[0]
            elif bootstrap.participant_display_name:
                current_full_name_full = bootstrap.participant_display_name.strip()
                current_full_name = current_full_name_full.split()[0] if current_full_name_full else None

            hydrated_name: str | None = current_full_name
            if not hydrated_name:
                for s in sorted(
                    bucket.summaries, key=lambda x: x.step_number, reverse=True,
                ):
                    candidate = s.verbatim.get("name")
                    if isinstance(candidate, str) and candidate.strip():
                        hydrated_name = candidate.strip().split()[0]
                        current_full_name_full = candidate.strip()
                        break

            # Sweep `prior_pages`: overwrite every stale `name` in old summaries
            # so the prompt's prior_steps block can't recall an outdated value
            # when the agent answers "what's my name". The bucket is keyed by
            # (tenant_id, participant_id) so all summaries belong to the same
            # person — current name is the truthful one for every summary.
            if current_full_name_full:
                for step_key, step_payload in hydrated_prior.items():
                    if isinstance(step_payload, dict) and "name" in step_payload:
                        step_payload["name"] = current_full_name_full

            bootstrap = bootstrap.model_copy(update={
                "mode": "page_handoff",
                "prior_pages": hydrated_prior,
                "participant_display_name": hydrated_name,
            })

    # Diagnostic boundary log — proves what the new session inherits BEFORE
    # FormState is created. Identifiers + shape only; no raw values.
    log.info(
        "session_create_resolved_bootstrap",
        session_id=session_id,
        tenant_id=req.tenant_id,
        participant_id=req.participant_id,
        step=req.step,
        bootstrap_mode=bootstrap.mode,
        prior_pages_keys=list(bootstrap.prior_pages.keys()) if bootstrap.prior_pages else [],
        cross_screen_enabled=settings.onboarding_cross_screen_context_enabled,
    )

    # Seed FormState.values from whichever side provided pre-fill data. Explicit
    # initial_state still wins (it is shape-stable {section: {field: v}});
    # otherwise current_page_values from bootstrap is used.
    seed_values = req.initial_state if req.initial_state else bootstrap.current_page_values

    state = FormState(
        session_id=session_id,
        step_id=req.step,
        participant_id=req.participant_id,
        tenant_id=req.tenant_id,
        locale=req.locale,
        values=_build_initial_values(seed_values),
    )
    state.recompute_completion(req.schema)

    await repo.create_session(
        state, req.schema, ttl_sec=settings.session_max_sec, bootstrap=bootstrap,
    )

    # Track this session in the per-participant index so on-call tooling can
    # enumerate sessions for "the assistant forgot me" debug requests.
    if settings.onboarding_cross_screen_context_enabled and req.tenant_id:
        ctx_repo = UserContextRepo(repo._r)
        await ctx_repo.add_session_to_index(req.tenant_id, req.participant_id, session_id)

    _scheme = "wss" if request.url.scheme == "https" else "ws"
    ws_url = f"{_scheme}://{request.url.netloc}/ws/onboarding/{session_id}"

    return CreateSessionResponse(
        session_id=session_id,
        ws_url=ws_url,
        expires_at=expires_at,
        resumption_handle=None,
    )


@router.get("/v1/onboarding/session/{session_id}/state", response_model=FormState)
async def get_state(
    session_id: str,
    repo: FormStateRepo = Depends(get_repo),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_participant_id: str | None = Header(default=None, alias="X-Participant-Id"),
) -> FormState:
    state = await repo.get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    # Cross-tenant isolation guard. Only enforced when caller supplied
    # identity headers — older mobile clients without the headers fall back to
    # today's lookup-by-session-id behaviour. New clients SHOULD send both.
    if x_participant_id is not None:
        await repo.assert_session_owner(session_id, x_tenant_id, x_participant_id)

    return state


@router.put("/v1/onboarding/session/{session_id}/state", response_model=FormState)
async def update_state(
    session_id: str,
    req: UpdateStateRequest,
    repo: FormStateRepo = Depends(get_repo),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_participant_id: str | None = Header(default=None, alias="X-Participant-Id"),
) -> FormState:
    if x_participant_id is not None:
        await repo.assert_session_owner(session_id, x_tenant_id, x_participant_id)
    if await repo.is_ws_locked(session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Session has an active voice connection. "
                "Close the WebSocket before updating state."
            ),
        )
    state = await repo.get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    schema = await repo.get_schema(session_id)

    # Merge app values into state (app writes, source=app)
    for section_id, section_data in req.values.items():
        if isinstance(section_data, list):
            state.values[section_id] = [
                {
                    fid: FieldValue(value=fv, source=FieldSource.app).model_dump(mode="json")
                    for fid, fv in row.items()
                }
                for row in section_data
            ]
        elif isinstance(section_data, dict):
            if section_id not in state.values:
                state.values[section_id] = {}
            for fid, fv in section_data.items():
                state.values[section_id][fid] = FieldValue(
                    value=fv, source=FieldSource.app
                ).model_dump(mode="json")

    if schema:
        state.recompute_completion(schema)
    state.touch()
    await repo.save_state(state, ttl_sec=settings.session_max_sec)
    return state


@router.post("/v1/onboarding/session/{session_id}/complete", status_code=200)
async def complete_session(
    session_id: str,
    repo: FormStateRepo = Depends(get_repo),
) -> dict:
    state = await repo.get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    transcript = await repo.get_transcript(session_id)

    schema = await repo.get_schema(session_id)

    state.completed = True
    state.completed_at = datetime.now(UTC)
    await repo.save_state(state, ttl_sec=settings.session_max_sec)

    # Persist a StepSummary into the cross-screen bucket BEFORE firing the
    # webhook. Idempotent on (participant_id, step_number) — a subsequent
    # WS-close flush for the same step is a safe no-op overwrite. Skipped
    # entirely when the feature flag is off or tenant_id is unknown
    # (legacy sessions created before the field was required).
    if (
        settings.onboarding_cross_screen_context_enabled
        and state.tenant_id
    ):
        try:
            ctx_repo = UserContextRepo(repo._r)
            step_number = _step_id_to_number(state.step_id)
            step_label = schema.step_label if schema else state.step_id
            summary = build_summary(
                state,
                step_number=step_number,
                step_label=step_label,
                completed_at=state.completed_at,
            )
            await ctx_repo.put_step_summary(state.tenant_id, state.participant_id, summary)
            log.info(
                "complete_session_summary_written",
                session_id=session_id,
                tenant_id=state.tenant_id,
                participant_id=state.participant_id,
                step=state.step_id,
                step_number=step_number,
            )
        except Exception:
            # Never fail completion because of a context-bucket write error;
            # the webhook is the contract that matters here.
            log.exception(
                "complete_session_summary_write_failed",
                session_id=session_id,
                tenant_id=state.tenant_id,
                participant_id=state.participant_id,
            )

    payload = {
        "event": "onboarding.session.completed",
        "session_id": session_id,
        "participant_id": state.participant_id,
        "tenant_id": state.tenant_id,
        "step": state.step_id,
        "state": state.model_dump(mode="json"),
        "transcript": transcript,
        "started_at": state.started_at.isoformat(),
        "completed_at": state.completed_at.isoformat(),
    }

    delivered = await fire_webhook(
        url=settings.app_webhook_url,
        event="onboarding.session.completed",
        payload=payload,
        secret=settings.app_webhook_secret,
        max_retries=settings.onboarding_webhook_max_retries,
    )

    return {
        "session_id": session_id,
        "completed": True,
        "webhook_delivered": delivered,
    }


# ── Client validation error reporting (telemetry) ─────────────────────────────


@router.post(
    "/v1/onboarding/session/{session_id}/errors",
    status_code=204,
)
async def report_client_validation_error(
    session_id: str,
    body: ClientValidationErrorRequest,
    repo: FormStateRepo = Depends(get_repo),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_participant_id: str | None = Header(default=None, alias="X-Participant-Id"),
) -> Response:
    """Record a client-reported validation error for telemetry / future tuning.

    The mobile client posts here whenever its own validator rejects a typed
    or voice-derived value before it would have reached the server. Server
    persists the entry under ``sena:onboarding:errors:{session_id}`` with a
    7-day TTL; nothing in the live decision path reads it.

    Returns 204 No Content on success. Returns 404 when the session does not
    exist (mirrors the privacy-preserving 404 behaviour of GET/PUT state —
    we deliberately do not leak ownership info on a missing session).
    """
    state = await repo.get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    # Mirror state-route guard. Both headers gate the check together — older
    # clients without headers fall through, matching today's behaviour.
    if x_participant_id is not None:
        await repo.assert_session_owner(session_id, x_tenant_id, x_participant_id)
    await repo.append_client_validation_error(
        session_id,
        body.model_dump(mode="json"),
    )
    log.info(
        "client_validation_error_recorded",
        session_id=session_id,
        error_type=body.error_type,
        input_method=body.input_method,
        field_id=body.field_id,
    )
    return Response(status_code=204)


# ── Diagnostic (non-production only) ──────────────────────────────────────────

@router.get("/v1/onboarding/_diag/bucket")
async def diag_bucket(
    repo: FormStateRepo = Depends(get_repo),
    tenant_id: str = Query(..., min_length=1),
    participant_id: str = Query(..., min_length=1),
) -> dict:
    """Inspect the cross-screen bucket for a (tenant_id, participant_id) pair.

    Dev-only — returns 404 in production. Lets the test harness or on-call
    engineer confirm the bucket state without redis-cli access. Returns shape
    counts only — never the verbatim summaries — to keep PII off the wire.
    """
    if settings.environment == "production":
        raise HTTPException(status_code=404, detail="Not found")
    ctx_repo = UserContextRepo(repo._r)
    bucket = await ctx_repo.get_bucket(tenant_id, participant_id)
    return {
        "tenant_id": tenant_id,
        "participant_id": participant_id,
        "bucket_empty": bucket.is_empty(),
        "summary_count": len(bucket.summaries),
        "step_numbers": [s.step_number for s in bucket.summaries],
        "step_labels": [s.step_label for s in bucket.summaries],
        "cross_screen_enabled": settings.onboarding_cross_screen_context_enabled,
    }


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health/live")
async def health_live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready(repo: FormStateRepo = Depends(get_repo)) -> dict:
    try:
        await repo._r.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
