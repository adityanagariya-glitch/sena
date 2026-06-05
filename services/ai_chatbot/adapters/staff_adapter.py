"""Staff service adapter: HTTP calls with import fallback.

Calls Staff API at /query/stream and /query with fallback to
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
        """Stream from the staff service's INDEPENDENT section endpoint.

        `staff_scope` ("staff" | "client") picks the isolated endpoint:
          • "client" → /client/query/stream  (participant info)
          • else     → /staff/query/stream   (shifts/rosters/team)
        The two sections share no tools server-side, so there's no cross-section
        leakage regardless of what's asked.
        """
        scope = "client" if ctx.get("staff_scope") == "client" else "staff"
        path = f"/{scope}/query/stream"
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
        async for event in self._stream_sse(path, payload, headers):
            yield event
