"""Streaming response utilities: SSE generation, stdout capture."""
import asyncio
import io
import logging
import json
import sys
from contextlib import redirect_stdout
from typing import AsyncGenerator, Optional, Dict, Any

logger = logging.getLogger(__name__)


class TokenCapture(io.StringIO):
    """StringIO that intercepts print() calls to yield tokens as they appear."""

    def __init__(self):
        super().__init__()
        self.tokens: asyncio.Queue = asyncio.Queue()

    def write(self, s: str) -> int:
        """Capture written text and queue for streaming."""
        if s:
            # Non-blocking queue.put_nowait (assumes async context)
            try:
                self.tokens.put_nowait(s)
            except asyncio.QueueFull:
                logger.warning("Token queue overflow, dropping token")
        return super().write(s)


async def sse_event(event_type: str, data: Dict[str, Any]) -> str:
    """Format a single SSE event.

    Args:
        event_type: Event type for logging/debugging
        data: Payload dict (serialized to JSON)

    Returns:
        SSE-formatted string with data: {...} and trailing newlines
    """
    json_data = json.dumps(data)
    return f"data: {json_data}\n\n"


async def generate_stream(
    query: str,
    handler_fn,  # async callable that processes the query
    session_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[str, None]:
    """Generator that yields SSE events from a streaming handler.

    Args:
        query: User question
        handler_fn: Async function(query) → yields events
        session_id: For event metadata
        metadata: Additional metadata to include

    Yields:
        SSE-formatted event strings
    """
    metadata = metadata or {}

    # Send initial metadata event
    meta_event = await sse_event("meta", {
        "type": "meta",
        "session_id": session_id,
        **metadata,
    })
    yield meta_event

    try:
        # Call handler and stream its events
        async for event in handler_fn(query):
            if isinstance(event, dict):
                sse_str = await sse_event(event.get("type", "unknown"), event)
                yield sse_str
            else:
                # Raw string event
                yield event

        # Send completion event
        done_event = await sse_event("done", {
            "type": "done",
            "stop_reason": "end_turn",
        })
        yield done_event

    except Exception as e:
        logger.exception(f"Stream handler error: {e}")
        error_event = await sse_event("error", {
            "type": "error",
            "text": str(e),
        })
        yield error_event


async def capture_stdout_tokens(
    handler_fn,
    *args,
    **kwargs,
) -> AsyncGenerator[str, None]:
    """Run handler with stdout redirected to TokenCapture, yield tokens.

    Useful for capturing agent output token-by-token for streaming.

    Args:
        handler_fn: Sync or async function to run
        *args, **kwargs: Arguments to pass to handler

    Yields:
        Tokens captured from stdout
    """
    capture = TokenCapture()

    # Run handler with stdout redirected
    with redirect_stdout(capture):
        if asyncio.iscoroutinefunction(handler_fn):
            await handler_fn(*args, **kwargs)
        else:
            handler_fn(*args, **kwargs)

    # Drain remaining tokens
    while True:
        try:
            token = capture.tokens.get_nowait()
            yield token
        except asyncio.QueueEmpty:
            break
