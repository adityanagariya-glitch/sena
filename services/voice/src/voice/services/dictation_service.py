from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from voice.services.bedrock_service import BedrockService
from voice.services.redis_service import RedisService
from voice.services.transcribe_service import TranscribeService
from voice.repositories.voice_repo import VoiceRepository


DEFAULT_SECTIONS = {
    "participant_state": "",
    "support_actions": "",
    "incidents_risks": "",
    "medications_health": "",
    "outcomes_followup": "",
    "handover_notes": "",
}


class DictationService:
    def __init__(
        self,
        repo: VoiceRepository,
        redis_service: RedisService,
        bedrock: BedrockService,
        transcribe: TranscribeService,
    ) -> None:
        self.repo = repo
        self.redis = redis_service
        self.bedrock = bedrock
        self.transcribe = transcribe

    async def start_session(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        participant_id: UUID,
        staff_id: UUID,
        shift_id: UUID,
        objective: str,
    ):
        if objective != "CASE_NOTE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Only CASE_NOTE is allowed"
            )
        session = await self.repo.create_voice_session(
            db, tenant_id, participant_id, staff_id, shift_id, objective
        )
        await self.redis.save_session_state(
            str(session.id),
            {
                "draft_sections": DEFAULT_SECTIONS,
                "section_coverage": {k: 0.0 for k in DEFAULT_SECTIONS},
                "missing_topics": list(DEFAULT_SECTIONS.keys()),
                "history": [],
                "safety_category": "normal",
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

        normalized = await self.transcribe.normalize_turn(transcript, transcript_confidence)
        state = await self.redis.load_session_state(str(session_id))
        history = state.get("history", [])[-5:]
        model_input_snapshot = {
            "existing_draft": state.get("draft_sections", DEFAULT_SECTIONS),
            "section_coverage": state.get("section_coverage", {k: 0.0 for k in DEFAULT_SECTIONS}),
            "missing_topics": state.get("missing_topics", list(DEFAULT_SECTIONS.keys())),
        }

        ai_out, latency_ms = self.bedrock.run_dictation_turn(
            normalized.text,
            model_input_snapshot,
            history,
            tenant_id=str(session.tenant_id),
            session_id=str(session.id),
        )

        draft_updates = ai_out.get("draft_updates", {})
        merged = dict(state.get("draft_sections", DEFAULT_SECTIONS))
        for key, value in draft_updates.items():
            if key in merged and isinstance(value, str) and value.strip():
                merged[key] = value.strip()

        section_coverage = ai_out.get("section_coverage", {})
        missing_topics = ai_out.get("missing_topics", [])
        score = float(ai_out.get("overall_completeness_score", 0.0))
        safety_category = ai_out.get("safety_category", "normal")
        reply = str(ai_out.get("agent_reply", "Please continue with your notes."))

        history.append({"speaker": "worker", "text": normalized.text})
        history.append({"speaker": "agent", "text": reply})

        await self.redis.save_session_state(
            str(session_id),
            {
                "draft_sections": merged,
                "section_coverage": section_coverage,
                "missing_topics": missing_topics,
                "history": history[-10:],
                "safety_category": safety_category,
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
            section_coverage=section_coverage,
            missing_topics=missing_topics,
        )
        await self.repo.update_session_progress(
            db=db,
            session_id=session.id,
            draft_preview=" ".join([v for v in merged.values() if v]).strip(),
            section_coverage=section_coverage,
            missing_topics=missing_topics,
        )

        return {
            "agent_reply": reply,
            "draft_preview": " ".join([v for v in merged.values() if v]).strip(),
            "completeness_score": score,
            "missing_topics": missing_topics,
            "latency_ms": latency_ms,
        }
