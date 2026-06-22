import logging
from datetime import datetime

from app.models.schemas import (
    MessageAnalysis,
    SentimentBatchRequest,
    SentimentBatchResponse,
    SentimentResult,
    RiskAssessment,
    BreakdownAssessment,
)
from app.services.bedrock_service import BedrockService, MessageAnalysisItem

logger = logging.getLogger(__name__)

_FALLBACK_ANALYSIS = MessageAnalysisItem(
    sentiment=SentimentResult(label="neutral", confidence=0.0, reason="Analysis unavailable for this message."),
    risk=RiskAssessment(level="low", indicators=[], reason="Analysis unavailable for this message."),
    breakdown=BreakdownAssessment(detected=False, reasons=[]),
    outcome="pending",
    recommended_action=None,
)


class SentimentBatchService:
    def __init__(self):
        self.bedrock = BedrockService()

    def analyse(self, request: SentimentBatchRequest) -> SentimentBatchResponse:
        messages = request.messages

        logger.info(
            f"Batch analysis [{request.conversation_id}] "
            f"for provider [{request.provider_id}] | messages={len(messages)}"
        )

        output = self.bedrock.analyse_batch(messages)
        analyses = output.message_analyses

        if len(analyses) != len(messages):
            logger.warning(
                f"[{request.conversation_id}] Model returned {len(analyses)} analyses "
                f"for {len(messages)} messages — filling missing entries with fallback."
            )

        classified = [
            MessageAnalysis(
                role=msg.role,
                text=msg.text,
                timestamp=msg.timestamp,
                sentiment=analysis.sentiment,
                risk=analysis.risk,
                breakdown=analysis.breakdown,
                outcome=analysis.outcome,
                recommended_action=analysis.recommended_action,
            )
            for i, msg in enumerate(messages)
            for analysis in [analyses[i] if i < len(analyses) else _FALLBACK_ANALYSIS]
        ]

        return SentimentBatchResponse(
            conversation_id=request.conversation_id,
            provider_id=request.provider_id,
            messages=classified,
            messages_analysed=len(messages),
            period_start=min(m.timestamp for m in messages),
            period_end=max(m.timestamp for m in messages),
            analysed_at=datetime.utcnow(),
            token_usage=output.token_usage,
        )
