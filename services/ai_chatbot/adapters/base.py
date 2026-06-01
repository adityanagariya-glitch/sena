"""ServiceAdapter abstract base: contract for Staff and Policy services.

All adapters inherit from this and implement:
  - call_query(question, ctx) → response
  - call_streaming(question, ctx) → AsyncGenerator[event]
  - health_check() → bool
"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ServiceAdapter(ABC):
    """Abstract base for service adapters (Staff, Policy, etc.)."""

    def __init__(self, service_name: str, base_url: str, jwt_secret: str):
        """Initialize adapter.

        Args:
            service_name: Display name (staff, policy)
            base_url: Service URL (http://localhost:8000)
            jwt_secret: JWT secret for token validation
        """
        self.service_name = service_name
        self.base_url = base_url
        self.jwt_secret = jwt_secret

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
