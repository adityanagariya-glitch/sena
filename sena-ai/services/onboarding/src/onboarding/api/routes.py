from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel

from onboarding.api.deps import get_repo
from onboarding.core.settings import settings
from onboarding.models.form_state import FieldSource, FieldValue, FormState
from onboarding.models.schema_spec import StepSchema
from onboarding.models.session_bootstrap import SessionBootstrap
from onboarding.repositories.state_repo import FormStateRepo
from onboarding.repositories.user_context_repo import UserContextRepo
from onboarding.services.cross_screen_context import build_summary
from onboarding.services.webhook import fire_webhook

log = structlog.get_logger(__name__)
router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
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
            ]
        elif isinstance(section_data, dict):
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
    repo: FormStateRepo = Depends(get_repo),
) -> CreateSessionResponse:
    session_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.onboarding_session_max_min)

    # Resolve bootstrap envelope. Explicit takes precedence; legacy initial_state
    # is wrapped into a synthesised bootstrap so older clients keep working.
    bootstrap = req.bootstrap or SessionBootstrap.from_initial_state(req.initial_state)

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
            bootstrap = bootstrap.model_copy(update={
                "mode": "page_handoff",
                "prior_pages": {
                    f"step:{s.step_number}": {
                        **s.verbatim,
                        "_compressed": s.compressed,
                        "_step_label": s.step_label,
                    }
                    for s in bucket.summaries
                },
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

    ws_url = f"ws://localhost:{settings.onboarding_port}/ws/onboarding/{session_id}"

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
            detail="Session has an active voice connection. Close the WebSocket before updating state.",
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

    from datetime import timezone as _tz
    from datetime import datetime as _dt
    state.completed = True
    state.completed_at = _dt.now(_tz.utc)
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
