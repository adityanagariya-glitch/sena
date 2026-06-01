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
        """Stream query response from Policy /query/stream.

        Policy service performs classification and may block queries.
        Yields events with classification labels.

        Args:
            question: User question
            ctx: Request context with jwt_token

        Yields:
            Event dicts (type, text, label, classification)
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
            logger.exception(f"Policy /query/stream call failed: {e}")
            yield {"type": "error", "text": str(e)}
