"""Policy service adapter: HTTP calls to policy /query/stream.

Calls Policy API with JWT auth and parses SSE event stream.
"""
import logging
from typing import AsyncGenerator, Dict, Any
import httpx

from adapters.base import ServiceAdapter

logger = logging.getLogger(__name__)


class PolicyAdapter(ServiceAdapter):
    """Adapter for Policy/Proc service."""

    async def health_check(self) -> bool:
        """Check if Policy service is healthy."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code < 400
        except Exception as e:
            logger.warning(f"Policy health check failed: {e}")
            return False

    async def call_query(
        self, question: str, ctx: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute non-streaming query (fallback: not implemented for Policy).

        Args:
            question: User question
            ctx: Request context with jwt_token

        Returns:
            Placeholder response
        """
        logger.warning("Policy non-streaming query not implemented, use call_streaming instead")
        return {
            "response": "Policy service requires streaming mode",
            "session_id": ctx.get("session_id", "unknown"),
        }

    async def call_streaming(
        self, question: str, ctx: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream query response from Policy /query/stream (shared pooled client).

        Policy service performs classification and may block queries; it yields
        events with classification labels.
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
        async for event in self._stream_sse("/query/stream", payload, headers):
            yield event
