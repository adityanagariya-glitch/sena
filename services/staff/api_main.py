"""
FastAPI wrapper for staff service.
Exposes /query/stream endpoint for ai_chatbot gateway testing.

This allows the gateway to call staff service via HTTP.
"""
from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
import logging
from typing import AsyncGenerator, Optional

from router import process_query
from auth import authenticate_with_jwt


class QueryRequest(BaseModel):
    question: Optional[str] = None
    session_id: Optional[str] = None
    session_title: Optional[str] = None
    is_new_chat: bool = False

logger = logging.getLogger(__name__)

app = FastAPI(
    title="SENA Staff API",
    version="1.0.0",
    description="Staff service HTTP API wrapper for testing",
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/query/stream")
async def query_stream(
    req: QueryRequest,
    authorization: str = Header(None),
):
    """
    Stream query response from staff service.

    Args:
        req: JSON body with question + optional session fields
        authorization: JWT token in Authorization header

    Returns:
        Server-Sent Events stream
    """
    question = req.question
    session_id = req.session_id
    token = (authorization or "").replace("Bearer ", "").strip()
    logger.info(f"Staff API: Query received: '{question}'")

    async def event_stream() -> AsyncGenerator[str, None]:
        if not question:
            yield f"data: {json.dumps({'type': 'error', 'text': 'Question is required'})}\n\n"
            return

        # Authenticate the incoming JWT so process_query has the user context
        # (shifts/payroll/etc. are user-scoped and need a valid token).
        if not token:
            yield f"data: {json.dumps({'type': 'error', 'text': 'Missing Authorization bearer token'})}\n\n"
            return
        if not authenticate_with_jwt(token):
            yield f"data: {json.dumps({'type': 'error', 'text': 'Invalid or expired JWT token'})}\n\n"
            return

        try:
            # Call the router's process_query function
            logger.info(f"Calling process_query...")
            result = process_query(question)

            # Yield as SSE events
            logger.info(f"Got response from process_query")

            # Send metadata
            yield f"data: {json.dumps({'type': 'meta', 'session_id': session_id or 'staff-session'})}\n\n"

            # Send response. Send it whole — splitting on whitespace would strip
            # newlines and collapse markdown tables/lists onto one line.
            if isinstance(result, str):
                yield f"data: {json.dumps({'type': 'token', 'text': result})}\n\n"

            # Send done
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            logger.info(f"Stream complete")

        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8601,
        log_level="info",
    )
