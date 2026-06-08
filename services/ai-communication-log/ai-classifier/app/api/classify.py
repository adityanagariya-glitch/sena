import logging
from fastapi import APIRouter, HTTPException, status

from app.models.schemas import ClassificationRequest, ClassificationResponse
from app.services.classification_service import ClassificationService

logger = logging.getLogger(__name__)
router = APIRouter()

# Single instance — BedrockService boto3 client is thread-safe
_classification_service = ClassificationService()


@router.post(
    "/classify",
    response_model=ClassificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Classify a communication log message",
    description=(
        "Accepts a current message and optional conversation history. "
        "Returns multi-label classification (emergency / inappropriate / normal) "
        "with confidence scores and reasons for each label. "
        "Data is scoped to the provider_id — never cross-contaminated."
    ),
    responses={
        200: {"description": "Classification successful"},
        422: {"description": "Validation error in request body"},
        500: {"description": "Internal classification error (Bedrock or parsing failure)"},
    },
)
async def classify_communication(
    request: ClassificationRequest,
) -> ClassificationResponse:
    """
    Main classification endpoint.

    Called by the Sena backend whenever a new message is sent
    in a support_worker ↔ client conversation.

    The caller (other team) decides what action to take based on
    the labels returned — this service only classifies.
    """
    try:
        result = _classification_service.classify(request)
        return result

    except ValueError as e:
        # Model returned unexpected output
        logger.error(f"Classification parsing error for [{request.conversation_id}]: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Classification failed — model output could not be parsed: {str(e)}",
        )

    except RuntimeError as e:
        # Bedrock API error
        logger.error(f"Bedrock error for [{request.conversation_id}]: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upstream model error: {str(e)}",
        )

    except Exception as e:
        logger.exception(f"Unexpected error for [{request.conversation_id}]: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during classification.",
        )
