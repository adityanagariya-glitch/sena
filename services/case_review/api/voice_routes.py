"""Voice case-note dictation — session-create REST + Gemini Live WebSocket.

Reuses the shared ``shared.src.sena_common.voice`` engine. Mobile-proxy model: the server
holds ephemeral Redis state during the session; on ``finalize_note`` the mobile
client assembles + submits the note to the app backend (this service writes
nothing to Postgres for the voice flow).

Tenant isolation (NDIS, legally mandated):
  * Redis keys are tenant-scoped — ``FormStateRepo(key_prefix="sena:case_review",
    tenant_id=...)``. A caller presenting a different tenant builds a different
    key and simply cannot see the session.
  * ``assert_session_owner`` is called on load as defense-in-depth.
  * Staff-only: a non-staff role is rejected before any session work.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from api.deps import get_auth_context, voice_redis_client
from core.settings import settings
from models.schemas import AuthContext
from voice.casenote_schema import CASE_NOTE_SCHEMA
from voice.drafter import run_draft
from voice.tool_decls import CASE_NOTE_FUNCTION_DECLS, CASE_NOTE_KNOWN_TOOLS
from shared.src.sena_common.voice import (
    FormStateRepo,
    GeminiLiveSession,
    MobileBridge,
    ToolDispatcher,
    VoiceEngineConfig,
    build_system_prompt,
)
from shared.src.sena_common.voice.form_state import FieldSource, FormState
from shared.src.sena_common.voice.gemini_live import UsageFeature
from shared.src.sena_common.voice.turn_payload import NextTarget, Participant, StepInfo, TurnPayload, VisibleField

log = structlog.get_logger(__name__)

voice_router = APIRouter()

_KEY_PREFIX = "sena:case_review"
_STEP_ID = "staff_case_note"
_STEP_LABEL = "Case Note"
_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "voice" / "prompts"
_STAFF_ROLES = {"worker", "staff", "support_worker", "admin"}


def _is_staff(roles: list[str]) -> bool:
    return any(r.strip().lower() in _STAFF_ROLES for r in roles)


def _voice_config() -> VoiceEngineConfig:
    return VoiceEngineConfig(
        gemini_api_key=settings.gemini_api_key,
        gemini_live_model_id=settings.gemini_live_model_id,
        prompts_dir=_PROMPTS_DIR,
        grounding_enabled=settings.voice_grounding_enabled,
        screen_state_max_bytes=settings.screen_state_max_bytes,
        session_max_sec=settings.voice_session_max_sec,
        silence_timeout_sec=settings.voice_silence_timeout_sec,
        tool_state_channel=True,
        debug=settings.debug,
    )


def _repo_for(tenant_id: str) -> FormStateRepo:
    return FormStateRepo(voice_redis_client, key_prefix=_KEY_PREFIX, tenant_id=tenant_id)


def _build_initial_turn(state: FormState) -> TurnPayload:
    """Build TurnPayload from actual Redis state so Gemini gets the real form context."""
    visible_fields: list[VisibleField] = []
    has_any_value = False
    for section in CASE_NOTE_SCHEMA.sections:
        if not section.fields:
            continue
        section_values = state.values.get(section.id, {})
        for field_spec in section.fields:
            field_val = section_values.get(field_spec.id)
            value = field_val.value if field_val else None
            if value not in (None, "", [], {}):
                has_any_value = True
            visible_fields.append(
                VisibleField(
                    path=f"{section.id}.{field_spec.id}",
                    label=field_spec.label or field_spec.id,
                    type=str(field_spec.type),
                    required=field_spec.required is not False,
                    readonly=False,
                    value=value,
                )
            )
    next_target: NextTarget | None = None
    for vf in visible_fields:
        if vf.required and not vf.readonly and vf.value in (None, "", [], {}):
            next_target = NextTarget(path=vf.path, label=vf.label, reason="next_required")
            break
    return TurnPayload(
        participant=Participant(first_name="", display_name=""),
        step=StepInfo(id=_STEP_ID, label=_STEP_LABEL, number=1),
        bootstrap_mode="returning_same_page" if has_any_value else "new_user",
        prior_steps={},
        visible_fields=visible_fields,
        next_target=next_target,
    )


# ── Session create (staff-only) ───────────────────────────────────────────────


class CreateVoiceSessionRequest(BaseModel):
    client_id: str
    shift_id: str
    initial_values: dict[str, dict[str, Any]] = {}


class CreateVoiceSessionResponse(BaseModel):
    session_id: str
    ws_url: str


@voice_router.post(
    "/v1/case-review/voice/session",
    response_model=CreateVoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_voice_session(
    body: CreateVoiceSessionRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> CreateVoiceSessionResponse:
    """Create a tenant-scoped ephemeral voice session for case-note dictation."""
    if not _is_staff(auth.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "not_staff", "message": "Voice case notes are staff-only"},
        )
    tenant_id = str(auth.tenant_id)
    session_id = uuid.uuid4().hex
    state = FormState(
        session_id=session_id,
        step_id=_STEP_ID,
        participant_id=body.client_id,
        tenant_id=tenant_id,
    )
    for section_id, fields in body.initial_values.items():
        for field_id, value in fields.items():
            if value is not None:
                state.set_field(section_id, field_id, value, source=FieldSource.system, confidence=0.9)
    await _repo_for(tenant_id).save_state(state, ttl_sec=settings.voice_session_max_sec)
    log.info(
        "voice_session_created",
        session_id=session_id,
        tenant_id=tenant_id,
        client_id=body.client_id,
        shift_id=body.shift_id,
    )
    return CreateVoiceSessionResponse(
        session_id=session_id,
        ws_url=f"/ws/case-review/voice/{session_id}",
    )


# ── Transcript draft (Bedrock extraction → initial_values for voice session) ──


class DraftTranscriptRequest(BaseModel):
    transcript: str


class DraftTranscriptResponse(BaseModel):
    initial_values: dict[str, dict[str, Any]]
    gaps_note: str | None = None
    filled_count: int


@voice_router.post(
    "/v1/case-review/voice/draft",
    response_model=DraftTranscriptResponse,
    status_code=status.HTTP_200_OK,
)
async def draft_from_transcript(
    body: DraftTranscriptRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> DraftTranscriptResponse:
    """Extract case note fields from a shift transcript via Bedrock Claude Sonnet."""
    if not _is_staff(auth.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "not_staff", "message": "Voice case notes are staff-only"},
        )
    initial_values, gaps_note = await run_draft(body.transcript)
    filled_count = sum(len(fields) for fields in initial_values.values())
    log.info(
        "voice_draft_done",
        tenant_id=str(auth.tenant_id),
        filled_count=filled_count,
    )
    return DraftTranscriptResponse(
        initial_values=initial_values,
        gaps_note=gaps_note,
        filled_count=filled_count,
    )


# ── Voice WebSocket ───────────────────────────────────────────────────────────


async def _close(ws: WebSocket, code_str: str, message: str, ws_code: int) -> None:
    try:
        await ws.send_text(json.dumps({"type": "error", "code": code_str, "message": message}))
        await ws.close(code=ws_code)
    except Exception:
        pass


@voice_router.websocket("/ws/case-review/voice/{session_id}")
async def case_review_voice_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()

    # ── Auth (dev_header mode) — validate BEFORE any data access. Headers are
    # the primary channel (the Flutter client sets them); browsers CANNOT set
    # headers on a WS upgrade, so fall back to query params for the in-browser
    # demo harness (?tenant_id=&participant_id=&roles=worker). ──
    qp = websocket.query_params
    tenant_id = websocket.headers.get("x-tenant-id") or qp.get("tenant_id")
    participant_id = websocket.headers.get("x-participant-id") or qp.get("participant_id")
    _roles_raw = websocket.headers.get("x-user-roles") or qp.get("roles", "")
    roles = [r for r in _roles_raw.split(",") if r.strip()]
    if not tenant_id:
        await _close(websocket, "unauthenticated", "Missing X-Tenant-Id", 4401)
        return
    if not _is_staff(roles):
        await _close(websocket, "not_staff", "Voice case notes are staff-only", 4403)
        return

    repo = _repo_for(tenant_id)

    # ── Load tenant-scoped state (wrong tenant → key miss → not found) ─────────
    state = await repo.get_state(session_id)
    if state is None:
        await _close(websocket, "session_not_found", "Session not found or expired", 4004)
        return

    # Defense-in-depth ownership check (tenant + participant).
    try:
        await repo.assert_session_owner(session_id, tenant_id, participant_id or state.participant_id)
    except HTTPException:
        await _close(websocket, "forbidden", "Session does not belong to caller", 4403)
        return

    # ── Single-writer WS lock ──────────────────────────────────────────────────
    if not await repo.acquire_ws_lock(session_id, ttl_sec=settings.voice_session_max_sec):
        await _close(websocket, "session_locked", "Another voice connection is active", 4009)
        return

    try:
        # Opening handshake — accept {"type":"hello"} or {"type":"start"}.
        try:
            hello = json.loads(await websocket.receive_text())
        except WebSocketDisconnect:
            return
        except json.JSONDecodeError:
            await _close(websocket, "protocol_error", 'Expected {"type":"hello"} first', 4008)
            return
        if hello.get("type") not in ("hello", "start"):
            await _close(websocket, "protocol_error", 'Expected {"type":"hello"} first', 4008)
            return

        await websocket.send_text(json.dumps({
            "type": "ready",
            "state": json.loads(state.model_dump_json()),
            "prompt_version": "v2",
            "coverage": CASE_NOTE_SCHEMA.voice_coverage,
        }))

        cfg = _voice_config()
        initial_turn = _build_initial_turn(state)
        system_instruction = build_system_prompt(
            initial_turn,
            grounding_enabled=cfg.grounding_enabled,
            voice_coverage=CASE_NOTE_SCHEMA.voice_coverage,
            prompts_dir=cfg.prompts_dir,
            tool_state_channel=cfg.tool_state_channel,
            template_name="case_note_system.md",
        )

        bridge = MobileBridge(websocket, timeout_sec=5.0)
        dispatcher = ToolDispatcher(
            bridge=bridge,
            known_tools=CASE_NOTE_KNOWN_TOOLS,
            submit_tool_name="finalize_note",
        )
        live = GeminiLiveSession(
            websocket=websocket,
            session_id=session_id,
            system_instruction=system_instruction,
            repo=repo,
            tool_dispatcher=dispatcher,
            mobile_bridge=bridge,
            config=cfg,
            usage_feature=UsageFeature.CASE_NOTE_DRAFTING,
            function_decls=CASE_NOTE_FUNCTION_DECLS,
            tenant_id=tenant_id,
            participant_id=state.participant_id,
        )
        await live.run()
    except WebSocketDisconnect:
        log.info("voice_ws_disconnect", session_id=session_id)
    except Exception:
        log.exception("voice_ws_error", session_id=session_id)
        await _close(websocket, "internal_error", "Internal server error", 1011)
    finally:
        await repo.release_ws_lock(session_id)
