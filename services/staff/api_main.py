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
import asyncio
from typing import AsyncGenerator, Optional

from router import process_query
from auth import authenticate_with_jwt


class QueryRequest(BaseModel):
    question: Optional[str] = None
    session_id: Optional[str] = None
    session_title: Optional[str] = None
    is_new_chat: bool = False

logger = logging.getLogger(__name__)


async def _error_stream(text: str) -> AsyncGenerator[str, None]:
    """Simple error event stream."""
    yield f"data: {json.dumps({'type': 'error', 'text': text})}\n\n"

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
    print(f"Staff API: Query received: '{question}'", flush=True)

    # Validate inputs BEFORE creating the generator
    if not question:
        return StreamingResponse(
            _error_stream("Question is required"),
            media_type="text/event-stream"
        )
    if not token:
        return StreamingResponse(
            _error_stream("Missing Authorization bearer token"),
            media_type="text/event-stream"
        )
    if not authenticate_with_jwt(token):
        return StreamingResponse(
            _error_stream("Invalid or expired JWT token"),
            media_type="text/event-stream"
        )

    async def event_stream() -> AsyncGenerator[str, None]:
        # Validations done above before creating this generator.
        # Call the router's process_query function.
        print(f"[STREAM] Calling process_query (in thread)...", flush=True)
        try:
            result = await asyncio.to_thread(process_query, question)
        except Exception as e:
            import traceback
            print(f"[STREAM ERR] process_query failed: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc(flush=True)
            yield f"data: {json.dumps({'type': 'error', 'text': f'Process query error: {str(e)}'})}\n\n"
            return

        print(f"[STREAM] Got response from process_query", flush=True)

        # Send metadata
        yield f"data: {json.dumps({'type': 'meta', 'session_id': session_id or 'staff-session'})}\n\n"

        # Send response. Send it whole — splitting on whitespace would strip
        # newlines and collapse markdown tables/lists onto one line.
        if isinstance(result, str):
            yield f"data: {json.dumps({'type': 'token', 'text': result})}\n\n"

        # Send done
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

        print(f"[STREAM] Complete", flush=True)

    return StreamingResponse(event_stream(), media_type="text/event-stream", status_code=200)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8601,
        log_level="info",
    )
