"""Staff service adapter: HTTP calls with import fallback.

Calls Staff API at /query/stream and /query with fallback to
direct Python import for testing/local development.
"""
import logging
import asyncio
from typing import AsyncGenerator, Dict, Any, Optional
import httpx

from adapters.base import ServiceAdapter

logger = logging.getLogger(__name__)


class StaffAdapter(ServiceAdapter):
    """Adapter for Staff API service."""

    async def health_check(self) -> bool:
        """Check if Staff API is healthy."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code < 400
        except Exception as e:
            logger.warning(f"Staff health check failed: {e}")
            return False

    async def call_query(
        self, question: str, ctx: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute non-streaming query (fallback: not implemented for Staff).

        Args:
            question: User question
            ctx: Request context with jwt_token

        Returns:
            Placeholder response
        """
        logger.warning("Staff non-streaming query not implemented, use call_streaming instead")
        return {
            "response": "Staff service requires streaming mode",
            "session_id": ctx.get("session_id", "unknown"),
        }

    async def call_streaming(
        self, question: str, ctx: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream query response from Staff /query/stream.

        Connects to Staff API and yields SSE events.

        Args:
            question: User question
            ctx: Request context with jwt_token

        Yields:
            Event dicts parsed from SSE stream
        """
        headers = {
            "Authorization": f"Bearer {ctx.get('jwt_token', '')}",
            "Content-Type": "application/json",
        }
        payload = {
            "question": question,
            "session_id": ctx.get("session_id"),
            "session_title": ctx.get("session_title"),
            "is_new_chat": ctx.get("is_new_chat", False),
        }

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/query/stream",
                    json=payload,
                    headers=headers,
                ) as resp:
                    resp.raise_for_status()
                    # Parse SSE stream (data: {...}\n\n)
                    buffer = ""
                    async for chunk in resp.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            line, buffer = buffer.split("\n\n", 1)
                            if line.startswith("data: "):
                                try:
                                    import json
                                    event = json.loads(line[6:])
                                    yield event
                                except Exception as e:
                                    logger.warning(f"Failed to parse SSE event: {e}")

        except Exception as e:
            logger.exception(f"Staff /query/stream call failed: {e}")
            yield {"type": "error", "text": str(e)}
