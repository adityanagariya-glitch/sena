import logging
from fastapi import APIRouter, HTTPException, status

from app.models.schemas import SentimentBatchRequest, SentimentBatchResponse
from app.services.sentiment_batch_service import SentimentBatchService
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

_sentiment_batch_service = SentimentBatchService()


@router.post(
    "/sentiment-batch",
    response_model=SentimentBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch sentiment analysis for a conversation window",
    description=(
        "Accepts a batch of messages from a timed conversation window. "
        "Returns full per-message analysis (sentiment, risk, breakdown, outcome, recommended_action). "
        "Called by the Sena backend on a debounce timer or message-count cap — "
        "whichever triggers first. Max batch size is configurable via BATCH_MAX_MESSAGES."
    ),
    responses={
        200: {"description": "Batch analysis successful"},
        422: {"description": "Validation error — empty list, or exceeds BATCH_MAX_MESSAGES"},
        500: {"description": "Internal analysis error (Bedrock or parsing failure)"},
    },
)
async def analyse_sentiment_batch(
    request: SentimentBatchRequest,
) -> SentimentBatchResponse:
    if len(request.messages) > settings.BATCH_MAX_MESSAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Too many messages: received {len(request.messages)}, "
                f"maximum allowed is {settings.BATCH_MAX_MESSAGES} (BATCH_MAX_MESSAGES)."
            ),
        )

    try:
        return _sentiment_batch_service.analyse(request)

    except ValueError as e:
        logger.error(f"Batch parsing error for [{request.conversation_id}]: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch analysis failed — model output could not be parsed: {str(e)}",
        )

    except RuntimeError as e:
        logger.error(f"Bedrock error for [{request.conversation_id}]: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upstream model error: {str(e)}",
        )

    except Exception as e:
        logger.exception(f"Unexpected error for [{request.conversation_id}]: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during batch analysis.",
        )
