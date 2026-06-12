import logging
from datetime import datetime

from app.core.config import settings
from app.models.schemas import ClassificationRequest, ClassificationResponse
from app.services.bedrock_service import BedrockService

logger = logging.getLogger(__name__)


class ClassificationService:
    """
    Orchestrates the end-to-end classification flow:
    1. Trims history to configured limit
    2. Calls Bedrock via BedrockService (returns BedrockOutput)
    3. Determines uncertainty from classification confidence scores
    4. Builds and returns the full ClassificationResponse
    """

    def __init__(self):
        self.bedrock = BedrockService()

    def classify(self, request: ClassificationRequest) -> ClassificationResponse:
        # ── 1. Trim history to last N messages ────────────────────────────────
        trimmed_history = request.history[-settings.CONVERSATION_HISTORY_LIMIT:]
        total_messages = len(trimmed_history) + 1  # +1 for current message

        logger.info(
            f"Classifying conversation [{request.conversation_id}] "
            f"for provider [{request.provider_id}] | "
            f"history={len(trimmed_history)} | current=1"
        )

        # ── 2. Call Bedrock ───────────────────────────────────────────────────
        output = self.bedrock.classify(
            current_message=request.current_message,
            history=trimmed_history,
        )

        # ── 3. Determine uncertainty (classification confidence only) ─────────
        is_uncertain = all(
            c.confidence < settings.CONFIDENCE_THRESHOLD
            for c in output.classifications
        )
        if is_uncertain:
            logger.warning(
                f"Low confidence on all classification labels for [{request.conversation_id}]"
            )

        # ── 4. Build response ─────────────────────────────────────────────────
        return ClassificationResponse(
            conversation_id=request.conversation_id,
            provider_id=request.provider_id,
            is_uncertain=is_uncertain,
            classifications=output.classifications,
            sentiment=output.sentiment,
            risk=output.risk,
            breakdown=output.breakdown,
            outcome=output.outcome,
            recommended_action=output.recommended_action,
            messages_analysed=total_messages,
            analysed_at=datetime.utcnow(),
        )
