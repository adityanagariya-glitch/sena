from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from voice.services.gemini_service import GeminiService
from voice.services.redis_service import RedisService
from voice.services.transcribe_service import TranscribeService
from voice.repositories.voice_repo import VoiceRepository


REQUIRED_FIELDS = [
    "first_name",
    "last_name",
    "phone",
    "date_of_birth",
    "address_street",
    "address_city",
    "address_state",
    "emergency_contact_name",
    "emergency_contact_phone",
]

ALL_FIELDS: dict[str, object] = {
    "first_name": None,
    "last_name": None,
    "email": None,
    "phone": None,
    "date_of_birth": None,
    "gender": None,
    "about_me": None,
    "preferred_language": "English",
    "interpreter_required": False,
    "address_street": None,
    "address_state": None,
    "address_city": None,
    "address_zip": None,
    "service_address_same": None,
    "service_address_street": None,
    "service_address_state": None,
    "service_address_city": None,
    "service_address_zip": None,
    "emergency_contact_name": None,
    "emergency_contact_relation": None,
    "emergency_contact_email": None,
    "emergency_contact_phone": None,
}


def _compute_missing(fields: dict) -> list[str]:
    return [f for f in REQUIRED_FIELDS if not fields.get(f)]


def _compute_completeness(fields: dict) -> float:
    filled = sum(1 for f in REQUIRED_FIELDS if fields.get(f))
    return round(filled / len(REQUIRED_FIELDS), 2)


class PersonalDetailsService:
    def __init__(
        self,
        repo: VoiceRepository,
        redis_service: RedisService,
        gemini: GeminiService,
        transcribe: TranscribeService,
    ) -> None:
        self.repo = repo
        self.redis = redis_service
        self.gemini = gemini
        self.transcribe = transcribe

    async def start_session(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        participant_id: UUID,
        staff_id: UUID,
        shift_id: UUID,
    ):
        session = await self.repo.create_voice_session(
            db,
            tenant_id=tenant_id,
            participant_id=participant_id,
            staff_id=staff_id,
            shift_id=shift_id,
            objective="PERSONAL_DETAILS",
        )
        initial_fields = dict(ALL_FIELDS)
        await self.redis.save_session_state(
            str(session.id),
            {
                "fields": initial_fields,
                "missing_fields": list(REQUIRED_FIELDS),
                "history": [],
                "completeness_score": 0.0,
            },
        )
        return session

    async def process_turn(
        self,
        db: AsyncSession,
        session_id: UUID,
        transcript: str,
        transcript_confidence: float,
        sequence_number: int,
    ) -> dict:
        session = await self.repo.get_session_by_id(db, session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        if session.status != "ACTIVE":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session not active")
        if session.objective != "PERSONAL_DETAILS":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session objective is not PERSONAL_DETAILS",
            )

        normalized = await self.transcribe.normalize_turn(transcript, transcript_confidence)
        state = await self.redis.load_session_state(str(session_id))

        current_fields = state.get("fields", dict(ALL_FIELDS))
        missing_fields = state.get("missing_fields", list(REQUIRED_FIELDS))
        history = state.get("history", [])[-5:]

        ai_out, latency_ms, token_usage = self.gemini.run_personal_details_turn(
            transcript=normalized.text,
            current_fields=current_fields,
            missing_fields=missing_fields,
            history=history,
        )

        # Merge non-null updates into current fields
        updates = ai_out.get("field_updates", {})
        merged = dict(current_fields)
        for key, value in updates.items():
            if key in merged and value is not None:
                merged[key] = value

        # If service address is same, copy from home address
        if merged.get("service_address_same") is True:
            merged["service_address_street"] = merged.get("address_street")
            merged["service_address_state"] = merged.get("address_state")
            merged["service_address_city"] = merged.get("address_city")
            merged["service_address_zip"] = merged.get("address_zip")

        new_missing = _compute_missing(merged)
        score = _compute_completeness(merged)
        reply = str(ai_out.get("agent_reply", "Could you please continue?"))

        history.append({"speaker": "participant", "text": normalized.text})
        history.append({"speaker": "agent", "text": reply})

        await self.redis.save_session_state(
            str(session_id),
            {
                "fields": merged,
                "missing_fields": new_missing,
                "history": history[-10:],
                "completeness_score": score,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        await self.repo.add_turn(
            db=db,
            tenant_id=session.tenant_id,
            session_id=session.id,
            sequence_number=sequence_number,
            transcript=normalized.text,
            transcript_confidence=normalized.confidence,
            agent_reply=reply,
            section_coverage={f: (1.0 if merged.get(f) else 0.0) for f in REQUIRED_FIELDS},
            missing_topics=new_missing,
        )
        await self.repo.update_session_progress(
            db=db,
            session_id=session.id,
            draft_preview=f"{merged.get('first_name', '')} {merged.get('last_name', '')}".strip(),
            section_coverage={f: (1.0 if merged.get(f) else 0.0) for f in REQUIRED_FIELDS},
            missing_topics=new_missing,
        )

        return {
            "agent_reply": reply,
            "fields": merged,
            "missing_fields": new_missing,
            "completeness_score": score,
            "latency_ms": latency_ms,
            "token_usage": token_usage,
        }

    async def end_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        ended_at: datetime,
    ) -> dict:
        session = await self.repo.get_session_by_id(db, session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        if session.status != "ACTIVE":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already ended")
        if session.objective != "PERSONAL_DETAILS":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session objective is not PERSONAL_DETAILS",
            )

        state = await self.redis.load_session_state(str(session_id))
        fields = state.get("fields", dict(ALL_FIELDS))
        missing = state.get("missing_fields", list(REQUIRED_FIELDS))
        score = _compute_completeness(fields)

        draft = await self.repo.create_personal_details_draft(
            db=db,
            tenant_id=session.tenant_id,
            session_id=session.id,
            participant_id=session.participant_id,
            staff_id=session.staff_id,
            fields_json=fields,
            completeness_score=score,
            missing_fields=missing,
        )

        await self.repo.mark_session_completed(db, session.id, ended_at)

        return {
            "draft_id": draft.id,
            "fields": fields,
            "completeness_score": score,
            "missing_fields": missing,
        }
