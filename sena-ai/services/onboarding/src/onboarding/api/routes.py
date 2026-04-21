from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from onboarding.api.deps import get_repo
from onboarding.core.settings import settings
from onboarding.models.form_state import FieldSource, FieldValue, FormState
from onboarding.models.schema_spec import StepSchema
from onboarding.repositories.state_repo import FormStateRepo
from onboarding.services.webhook import fire_webhook

router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    participant_id: str
    step: str
    schema: StepSchema
    initial_state: dict | None = None
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

def _build_initial_values(initial_state: dict | None) -> dict:
    """Wrap raw values dict from app into FieldValue format if not already wrapped."""
    if not initial_state:
        return {}
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

    state = FormState(
        session_id=session_id,
        step_id=req.step,
        participant_id=req.participant_id,
        tenant_id=req.tenant_id,
        locale=req.locale,
        values=_build_initial_values(req.initial_state),
    )
    state.recompute_completion(req.schema)

    await repo.create_session(state, req.schema, ttl_sec=settings.session_max_sec)

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
) -> FormState:
    state = await repo.get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return state


@router.put("/v1/onboarding/session/{session_id}/state", response_model=FormState)
async def update_state(
    session_id: str,
    req: UpdateStateRequest,
    repo: FormStateRepo = Depends(get_repo),
) -> FormState:
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

    from datetime import timezone as _tz
    from datetime import datetime as _dt
    state.completed = True
    state.completed_at = _dt.now(_tz.utc)
    await repo.save_state(state, ttl_sec=settings.session_max_sec)

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
