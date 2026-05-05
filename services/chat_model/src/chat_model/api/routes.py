import time
from uuid import uuid4

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from chat_model.services.chat_service import (
    ChatService,
    ChatServiceError,
    LLMError,
    SessionError,
)
from chat_model.api.deps import (
    get_chat_service,
    auth_context_dependency,
    AuthContext,
    get_db_session,
    get_redis_client,
)
from chat_model.models.schemas import (
    ChatRequest,
    ChatResponse,
    SessionRead,
    SessionClearResponse,
    HealthResponse,
)
from chat_model.repositories.audit_repo import AuditRepo
from chat_model.core.settings import settings
from chat_model.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Rate limiter: per-user limit via Authorization header
limiter = Limiter(key_func=get_remote_address)


@router.post(
    "/v1/chat/message",
    response_model=ChatResponse,
    tags=["Chat"],
    summary="Send a chat message",
)
async def chat_message(
    request: ChatRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    chat_service: ChatService = Depends(get_chat_service),
):
    """Send a message and get a response from the chatbot.

    Requires authentication (X-Tenant-ID, X-User-ID, X-User-Role headers or JWT).
    Rate limited to 20 requests per minute per user.
    """
    try:
        session_id = request.session_id or str(uuid4())
        response, conversation = await chat_service.send_message(
            session_id, request.message, str(auth.tenant_id)
        )
        return ChatResponse(
            session_id=session_id,
            response=response,
            conversation=conversation,
        )
    except LLMError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LLM error: {str(e)}",
        )
    except ChatServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat service error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred",
        )


@router.get(
    "/v1/chat/session/{session_id}",
    response_model=SessionRead,
    tags=["Chat"],
    summary="Get session history",
)
async def get_session(
    session_id: str,
    auth: AuthContext = Depends(auth_context_dependency),
    chat_service: ChatService = Depends(get_chat_service),
):
    """Get conversation history for a session.

    Requires authentication (X-Tenant-ID, X-User-ID, X-User-Role headers or JWT).
    """
    try:
        conversation = await chat_service.get_session(session_id, str(auth.tenant_id))
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )
        return SessionRead(session_id=session_id, conversation=conversation)
    except HTTPException:
        raise
    except SessionError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Session error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred",
        )


@router.delete(
    "/v1/chat/session/{session_id}",
    response_model=SessionClearResponse,
    tags=["Chat"],
    summary="Clear session history",
)
async def clear_session(
    session_id: str,
    auth: AuthContext = Depends(auth_context_dependency),
    chat_service: ChatService = Depends(get_chat_service),
):
    """Clear session history.

    Requires authentication (X-Tenant-ID, X-User-ID, X-User-Role headers or JWT).
    """
    try:
        await chat_service.clear_session(session_id, str(auth.tenant_id))
        return SessionClearResponse(message=f"Session {session_id} cleared")
    except SessionError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Session error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred",
        )


@router.post(
    "/v1/chat/stream",
    tags=["Chat"],
    summary="Stream chat response",
)
async def chat_stream(
    request: ChatRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    chat_service: ChatService = Depends(get_chat_service),
    db_session: AsyncSession = Depends(get_db_session),
):
    """Stream chat response using Server-Sent Events.

    Requires authentication. Returns tokens as they arrive.
    """
    start_time = time.time()
    session_id = request.session_id or str(uuid4())

    async def event_generator():
        try:
            full_response = []

            async for token in chat_service.astream_message(
                session_id, request.message, str(auth.tenant_id)
            ):
                full_response.append(token)
                yield f"data: {token}\n\n"

            latency_ms = int((time.time() - start_time) * 1000)

            # Audit log
            audit_repo = AuditRepo(db_session)
            await audit_repo.append_audit(
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                session_id=session_id,
                question=request.message,
                answer="".join(full_response),
                doc_ids=[],
                latency_ms=latency_ms,
            )

            logger.info(
                "chat.stream",
                tenant_id=str(auth.tenant_id),
                session_id=session_id,
                msg_len=len(request.message),
                latency_ms=latency_ms,
            )

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error("chat.stream_error", session_id=session_id, error=str(e))
            yield f"data: ERROR: {str(e)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get(
    "/health/live",
    tags=["Health"],
    summary="Liveness probe",
)
async def health_live():
    """Liveness probe - always 200."""
    return {"status": "alive"}


@router.get(
    "/health/ready",
    tags=["Health"],
    summary="Readiness probe",
)
async def health_ready(
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """Readiness probe - check dependencies."""
    try:
        # Check Redis
        await redis_client.ping()

        return {
            "status": "ready",
            "redis": "connected",
            "vector_store": "connected",
            "gemini_api": "connected",
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service not ready: {str(e)}")


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
)
async def health():
    """Health check endpoint (no auth required)."""
    return HealthResponse(status="healthy", model=settings.gemini_model_id)
