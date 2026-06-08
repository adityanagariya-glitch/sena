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
    2. Calls Bedrock via BedrockService
    3. Determines uncertainty
    4. Builds and returns the final response
    """

    def __init__(self):
        self.bedrock = BedrockService()

    def classify(self, request: ClassificationRequest) -> ClassificationResponse:
        # ── 1. Trim history to last N messages ────────────────────────────────
        trimmed_history = request.history[-settings.CONVERSATION_HISTORY_LIMIT :]
        total_messages = len(trimmed_history) + 1  # +1 for current message

        logger.info(
            f"Classifying conversation [{request.conversation_id}] "
            f"for provider [{request.provider_id}] | "
            f"history={len(trimmed_history)} | current=1"
        )

        # ── 2. Call Bedrock ───────────────────────────────────────────────────
        classifications = self.bedrock.classify(
            current_message=request.current_message,
            history=trimmed_history,
        )

        # ── 3. Determine uncertainty ──────────────────────────────────────────
        # Mark uncertain if ALL labels have confidence below threshold
        is_uncertain = all(
            c.confidence < settings.CONFIDENCE_THRESHOLD
            for c in classifications
        )

        if is_uncertain:
            logger.warning(
                f"Low confidence on all labels for conversation [{request.conversation_id}]"
            )

        # ── 4. Build response ─────────────────────────────────────────────────
        return ClassificationResponse(
            conversation_id=request.conversation_id,
            provider_id=request.provider_id,
            is_uncertain=is_uncertain,
            classifications=classifications,
            messages_analysed=total_messages,
            analysed_at=datetime.utcnow(),
        )
