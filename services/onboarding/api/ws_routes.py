"""
WebSocket route — Phase B: Gemini Live voice session for onboarding.

Endpoint: WSS /ws/onboarding/{session_id}

Protocol summary:
  Client → Server:
    Binary frames       — raw PCM16 16 kHz mono audio (continuous stream)
    {"type":"start"}    — first text frame; opens the Gemini connection
    {"type":"user_text","text":"..."} — typed input alternative
    {"type":"audio_end"}              — signal end-of-utterance (flush)
    {"type":"validation_failed","section_id":"...","field_id":"...","reason_human":"...","code":"...","repeatable_index":N?}
                                      — frontend validator rejected a value; upserted into
                                        pending_validation_errors + injected into Gemini stream
    {"type":"validation_cleared","section_id":"...","field_id":"...","repeatable_index":N?}
                                      — previously-failed field now passes; cleared from state
    {"type":"stop"}                   — client-initiated graceful close

  Server → Client:
    {"type":"ready","state":{...},"prompt_version":"v2"}  — session live
    Binary frames       — raw PCM16 24 kHz mono audio from Gemini
    {"type":"turn_start"}             — Gemini began speaking
    {"type":"turn_complete"}          — Gemini finished turn
    {"type":"interrupted"}            — user interrupted agent
    {"type":"user_said","text":"..."}  — input transcription
    {"type":"agent_said","text":"..."} — output transcription
    {"type":"go_away","time_left_ms":N} — Gemini session closing in N ms;
                                          client MUST call resume endpoint before
                                          time_left_ms elapses to avoid a hard drop
    {"type":"resumable","handle":"...","ttl_sec":N} — app-level resume handle on close
    {"type":"error","code":"...","message":"..."} — errors

WS lock semantics: exactly one active WS per session_id at a time.
A second connection attempt receives {"type":"error","code":"session_locked"} + close 4009.
"""
from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from onboarding.api.deps import get_repo
from onboarding.core.settings import settings
from voice.config import VoiceEngineConfig
from voice.gemini_live import GeminiLiveSession
from voice.mobile_bridge import MobileBridge
from voice.prompt_builder import build_system_prompt
from voice.resumption import build_replay_context, issue_handle, redeem_handle
from voice.state_repo import FormStateRepo
from voice.tools import ToolDispatcher
from voice.turn_payload import Participant, StepInfo, TurnPayload
from onboarding.repositories.user_context_repo import UserContextRepo
from onboarding.services.cross_screen_context import build_summary


log = structlog.get_logger(__name__)


ws_router = APIRouter()


@ws_router.websocket("/ws/onboarding/{session_id}")
async def onboarding_ws(
    websocket: WebSocket,
    session_id: str,
    resume: str | None = None,
    repo: FormStateRepo = Depends(get_repo),
) -> None:
    await websocket.accept()
    log.info("ws_connect session=%s resume=%s", session_id, bool(resume))

    # ── 1. Load state + schema from Redis ─────────────────────────────────────
    state = await repo.get_state(session_id)
    if state is None:
        await _close_with_error(websocket, "session_not_found", "Session not found or expired", 4004)
        return

    # ── 1b. Tenant ownership guard (defense-in-depth) ─────────────────────────
    # Onboarding Redis keys are flat (session-id only), so a guessed session_id
    # could otherwise read another tenant's session over the WS — the REST routes
    # already call assert_session_owner, but this WS route never did. Enforce it
    # when the client presents X-Tenant-Id (matches the REST contract). Header-less
    # legacy connections are allowed through but logged; FULL closure needs the
    # Flutter WS client to send X-Tenant-Id/X-Participant-Id (see followups.md).
    _hdr_tenant = websocket.headers.get("x-tenant-id")
    _hdr_participant = websocket.headers.get("x-participant-id")
    if _hdr_tenant:
        try:
            await repo.assert_session_owner(
                session_id, _hdr_tenant, _hdr_participant or state.participant_id
            )
        except HTTPException:
            await _close_with_error(
                websocket, "forbidden", "Session does not belong to caller", 4403
            )
            return
    else:
        log.warning("ws_ownership_check_skipped_no_tenant_header", session_id=session_id)

    schema = await repo.get_schema(session_id)
    if schema is None:
        await _close_with_error(websocket, "schema_not_found",
                                "Session schema missing — recreate the session", 4004)
        return

    # Load Rule 1 / Rule 2 bootstrap envelope (None for legacy sessions —
    # build_system_prompt accepts None and falls back to mode='new_user').
    bootstrap = await repo.get_bootstrap(session_id)

    # ── 2. Acquire single-writer WS lock ──────────────────────────────────────
    acquired = await repo.acquire_ws_lock(session_id, ttl_sec=settings.session_max_sec)
    if not acquired:
        await _close_with_error(websocket, "session_locked",
                                "Another voice connection is already active for this session", 4009)
        return

    # ── 3. Validate resumption handle / plain reconnect (Phase E) ────────────
    replay_context: str = ""
    if resume:
        valid = await redeem_handle(repo, resume, session_id)
        if not valid:
            await repo.release_ws_lock(session_id)
            await _close_with_error(websocket, "resume_invalid",
                                    "Resumption handle invalid, expired, or already used", 4010)
            return
        transcript = await repo.get_transcript(session_id)
        replay_context = build_replay_context(transcript, settings.resumption_replay_turns)
        log.info("ws_resuming session=%s replay_turns=%d", session_id, len(transcript))
    else:
        # No resume handle — fresh session start. Do NOT inject old transcript.
        # Injecting it causes Gemini to treat prior answers as already collected
        # and skip asking those fields. Proper resume uses ?resume=<handle>.
        pass

    try:

        # ── 4. Wait for the opening handshake ─────────────────────────────────
        # Accept either the v2 mobile client ({"type":"hello","client_proto":"v2"})
        # or the legacy / test-harness frame ({"type":"start"}). The frame is only
        # used as a go-ahead signal; nothing downstream reads it.
        _expected = 'Expected {"type":"hello","client_proto":"v2"} or {"type":"start"} as first message'
        try:
            raw = await websocket.receive_text()
            hello = json.loads(raw)
        except WebSocketDisconnect:
            return
        except json.JSONDecodeError:
            await _close_with_error(websocket, "protocol_error", _expected, 4008)
            return

        if hello.get("type") not in ("hello", "start"):
            await _close_with_error(websocket, "protocol_error", _expected, 4008)
            return

        # ── 5. Send "ready" with current form state ────────────────────────────
        await websocket.send_text(json.dumps({
            "type": "ready",
            "state": json.loads(state.model_dump_json()),
            "prompt_version": "v2",
            "coverage": schema.voice_coverage,
        }))

        # ── 6. Build system prompt + tool dispatcher + run Gemini bridge ──────

        participant_display_name = (
            bootstrap.participant_display_name
            if bootstrap and bootstrap.participant_display_name
            else ""
        )
        participant_first_name = (
            participant_display_name.split(" ", 1)[0] if participant_display_name else ""
        )

        initial_turn = TurnPayload(
            participant=Participant(
                first_name=participant_first_name,
                display_name=participant_display_name,
            ),
            step=StepInfo(
                id=schema.step_id,
                label=schema.step_label,
                number=getattr(schema, "step_number", 0) or 0,
            ),
            bootstrap_mode=(
                bootstrap.mode
                if bootstrap and bootstrap.mode in {
                    "new_user", "returning_same_page", "page_handoff"
                }
                else "new_user"
            ),
            prior_steps=(bootstrap.prior_pages if bootstrap and bootstrap.prior_pages else {}),
            visible_fields=[],
            next_target=None,
        )

        import onboarding
        from pathlib import Path

        voice_cfg = VoiceEngineConfig(
            gemini_api_key=settings.gemini_api_key,
            gemini_live_model_id=settings.gemini_live_model_id,
            prompts_dir=Path(next(iter(onboarding.__path__))).resolve() / "prompts",
            grounding_enabled=settings.onboarding_grounding_enabled,
            screen_state_max_bytes=settings.screen_state_max_bytes,
            session_max_sec=settings.session_max_sec,
            silence_timeout_sec=settings.onboarding_silence_timeout_sec,
            tool_state_channel=settings.onboarding_tool_state_channel,
            debug=settings.debug,
        )

        system_instruction = build_system_prompt(
            initial_turn,
            grounding_enabled=settings.onboarding_grounding_enabled,
            voice_coverage=(schema.voice_coverage if schema and schema.voice_coverage else None),
            prompts_dir=voice_cfg.prompts_dir,
            tool_state_channel=voice_cfg.tool_state_channel,
        )

        mobile_bridge = MobileBridge(
            websocket, timeout_sec=settings.onboarding_mobile_bridge_timeout_sec
        )

        def _on_incident(args: dict[str, object]) -> None:
            log.warning("incident_escalated", session_id=session_id, **args)

        tool_dispatcher = ToolDispatcher(
            bridge=mobile_bridge,
            on_incident=_on_incident,
        )

        # Seed the model with the live screen state so its FIRST greeting knows
        # which fields are already filled — no get_current_state round-trip, no
        # "these are already filled" reminder from the participant. Only when
        # the hello frame carried visible_fields (resume / fresh-empty skip it).
        # Derive from the FormState loaded above (`state`) + `schema` — works
        # regardless of what the hello frame carried. Walk every schema field,
        # read its current value from state.values[section][field].value.
        initial_state_text: str | None = None
        _empty = (None, "", [], {})
        filled_paths: list[str] = []
        empty_required_paths: list[str] = []
        state_values = state.values if state else {}
        for section in schema.sections:
            section_vals = state_values.get(section.id, {}) if isinstance(state_values, dict) else {}
            for field in (section.fields or []):
                fv = section_vals.get(field.id) if isinstance(section_vals, dict) else None
                value = fv.get("value") if isinstance(fv, dict) else fv
                path = f"{section.id}.{field.id}"
                if value not in _empty:
                    filled_paths.append(path)
                elif field.required:
                    empty_required_paths.append(path)

        if filled_paths or empty_required_paths:
            if not empty_required_paths:
                _action = (
                    "Everything required is already filled. Greet briefly and "
                    "ask if they want to change anything or submit. Do NOT walk "
                    "through fields one by one."
                )
            else:
                _first = empty_required_paths[0]
                _action = (
                    f"START by asking for THIS field only: {_first}. "
                    "Do NOT start from the top of the form. Do NOT ask about any "
                    "field listed as already filled. Skip every filled field and "
                    "ask only the empty required ones, in the order listed."
                )
            initial_state_text = (
                "[SCREEN STATE — read silently, do NOT read aloud] "
                "This is the live state of the current screen on session open. "
                "You already know what is filled — never ask the participant "
                "which fields are done. "
                f"Already filled (SKIP these, do NOT ask): {filled_paths}. "
                f"Empty required fields to collect IN THIS ORDER: {empty_required_paths}. "
                + _action
            )

        live_session = GeminiLiveSession(
            websocket=websocket,
            session_id=session_id,
            system_instruction=system_instruction,
            repo=repo,
            tool_dispatcher=tool_dispatcher,
            replay_context=replay_context or None,
            mobile_bridge=mobile_bridge,
            initial_state_text=initial_state_text,
            config=voice_cfg,
            # Phase 1.5 — pass auth context for per-turn usage logging. Sourced
            # from FormState (populated by POST /session from request headers,
            # NOT request body). When tenant_id is empty the emit defaults to
            # "unknown" — easy to grep + fix later.
            tenant_id=(state.tenant_id if state else None),
            user_id=None,  # Phase 1.6 — thread once route handler exposes user_id
            participant_id=(state.participant_id if state else None),
        )
        await live_session.run()

    except WebSocketDisconnect:
        log.info("ws_disconnect session=%s", session_id)
    except Exception:
        log.exception("ws_unhandled_error session=%s", session_id)
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "code": "internal_error",
                "message": "Internal server error",
            }))
        except Exception:
            pass
    finally:
        # ── Issue resumable handle on non-terminal close (Phase E) ────────────
        state_after = None
        try:
            state_after = await repo.get_state(session_id)
            if state_after and not state_after.completed:
                handle = await issue_handle(repo, session_id, settings.resumption_handle_ttl_sec)
                await websocket.send_text(json.dumps({
                    "type": "resumable",
                    "handle": handle,
                    "ttl_sec": settings.resumption_handle_ttl_sec,
                }))
                log.debug("resumable_envelope_sent session=%s handle=%.8s…", session_id, handle)
        except Exception:
            pass  # best-effort — WS may already be closed

        # ── Best-effort summary flush on clean WS close ───────────────────────
        # Idempotent on (participant_id, step_number): if POST /complete already
        # wrote, this overwrite is a safe no-op. The branch only runs when the
        # session has accumulated something worth preserving (transcript or
        # populated state) and a tenant is known.
        try:
            if (
                settings.onboarding_cross_screen_context_enabled
                and state_after is not None
                and state_after.tenant_id
                and (state_after.transcript_count > 0 or any(state_after.values.values()))
            ):
                from onboarding.api.routes import _step_id_to_number  # local import
                ctx_repo = UserContextRepo(repo._r)
                step_number = _step_id_to_number(state_after.step_id)
                step_label = schema.step_label if schema else state_after.step_id
                summary = build_summary(
                    state_after,
                    step_number=step_number,
                    step_label=step_label,
                )
                await ctx_repo.put_step_summary(
                    state_after.tenant_id, state_after.participant_id, summary,
                )
                try:
                    log.info(
                        "ws_close_summary_flushed",
                        session_id=session_id,
                        tenant_id=state_after.tenant_id,
                        participant_id=state_after.participant_id,
                        step=state_after.step_id,
                        step_number=step_number,
                    )
                except Exception:
                    pass  # Logging must never block a connection close.
            elif (
                settings.onboarding_cross_screen_context_enabled
                and state_after is not None
                and not state_after.tenant_id
            ):
                log.warning(
                    "ws_close_summary_skipped_no_tenant",
                    session_id=session_id,
                    participant_id=state_after.participant_id,
                    note="state.tenant_id empty — bucket write skipped",
                )
        except Exception:
            log.exception("ws_close_flush_failed session=%s", session_id)

        await repo.release_ws_lock(session_id)
        log.info("ws_lock_released session=%s", session_id)
        try:
            await websocket.close()
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _close_with_error(
    websocket: WebSocket,
    code: str,
    message: str,
    ws_code: int,
) -> None:
    try:
        await websocket.send_text(json.dumps({"type": "error", "code": code, "message": message}))
        await websocket.close(code=ws_code)
    except Exception:
        pass
