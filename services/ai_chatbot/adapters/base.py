"""ServiceAdapter abstract base: contract for Staff and Policy services.

All adapters inherit from this and implement:
  - call_query(question, ctx) → response
  - call_streaming(question, ctx) → AsyncGenerator[event]
  - health_check() → bool

A shared, pooled httpx.AsyncClient (set by the orchestrator) is reused across
calls so downstream requests keep TCP/TLS connections alive instead of paying a
fresh handshake per question. A concrete `_stream_sse` helper centralises the
SSE parsing so both adapters share one tested implementation.
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)


class ServiceAdapter(ABC):
    """Abstract base for service adapters (Staff, Policy, etc.)."""

    def __init__(
        self,
        service_name: str,
        base_url: str,
        jwt_secret: str,
        client: Optional[httpx.AsyncClient] = None,
    ):
        """Initialize adapter.

        Args:
            service_name: Display name (staff, policy)
            base_url: Service URL (http://localhost:8000)
            jwt_secret: JWT secret for token validation
            client: Shared pooled httpx.AsyncClient (reused for connection
                keep-alive). If None, each call opens a short-lived client.
        """
        self.service_name = service_name
        self.base_url = base_url
        self.jwt_secret = jwt_secret
        self.client = client

    async def _stream_sse(
        self, path: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """POST to `path` and yield parsed SSE `data:` events as dicts.

        Uses the shared pooled client when available (no per-call connection
        setup); otherwise falls back to a short-lived client.
        """
        url = f"{self.base_url}{path}"
        shared = self.client is not None
        client = self.client or httpx.AsyncClient(timeout=None)
        try:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        line, buffer = buffer.split("\n\n", 1)
                        if line.startswith("data: "):
                            try:
                                yield json.loads(line[6:])
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse SSE event: {e}")
        except Exception as e:
            logger.exception(f"{self.service_name} {path} call failed: {e}")
            yield {"type": "error", "text": str(e)}
        finally:
            if not shared:
                await client.aclose()

    @abstractmethod
    async def call_query(
        self, question: str, ctx: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a non-streaming query.

        Args:
            question: User question
            ctx: Request context (user_id, org_id, role, token)

        Returns:
            Response dict with at least "response" key
        """
        pass

    @abstractmethod
    async def call_streaming(
        self, question: str, ctx: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream a query response as events.

        Args:
            question: User question
            ctx: Request context (user_id, org_id, role, token)

        Yields:
            Event dicts (type, text, etc.)
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if service is healthy.

        Returns:
            True if service is responding
        """
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        pass
