"""Gateway extensions: /route endpoint, service adapter orchestration.

Integrates routing, adapter management, and circuit breaking into the gateway.
"""
import logging
from typing import AsyncGenerator, Dict, Any, Optional
from fastapi import HTTPException

from adapters import StaffAdapter, PolicyAdapter, handle_adapter_error
from router import route_query
from token_manager import cache_token, extract_claims
from circuit_breaker import can_call, record_success, record_failure

logger = logging.getLogger(__name__)


class ServiceOrchestrator:
    """Manages service adapters, routing, and circuit breaking."""

    def __init__(
        self,
        staff_url: str = "http://localhost:8001",
        policy_url: str = "http://localhost:8000",
        jwt_secret: str = "sena-local-qa-secret-change-in-prod",
    ):
        """Initialize orchestrator with service URLs.

        Args:
            staff_url: Staff API base URL
            policy_url: Policy API base URL
            jwt_secret: JWT secret for validation
        """
        self.staff_adapter = StaffAdapter("staff", staff_url, jwt_secret)
        self.policy_adapter = PolicyAdapter("policy", policy_url, jwt_secret)
        self.jwt_secret = jwt_secret

    async def route_and_stream(
        self,
        question: str,
        jwt_token: str,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Route question and stream response from appropriate service.

        Args:
            question: User question
            jwt_token: JWT token for authentication
            context: Request context (user_id, org_id, role, session_id)

        Yields:
            Event dicts (meta, token, done, error)
        """
        # Extract and cache token
        try:
            claims = await extract_claims(jwt_token)
            await cache_token(jwt_token, claims.get("user_id"), claims.get("org_id"))
        except Exception as e:
            logger.warning(f"Failed to cache token: {e}")

        # Route query
        routing = await route_query(question, context)
        logger.info(f"Query routed to: {routing['target_services']} ({routing['routing_reason']})")

        # Yield routing metadata
        yield {
            "type": "meta",
            "routing": routing,
            "session_id": context.get("session_id"),
        }

        # Out of scope — no service handles this question.
        if not routing["target_services"]:
            yield {
                "type": "token",
                "text": "This question is out of scope — I can only help with staff or policy questions.",
            }
            yield {"type": "done"}
            return

        # Call target service(s)
        for service_name in routing["target_services"]:
            # Check circuit breaker
            if not await can_call(service_name):
                logger.warning(f"Circuit breaker OPEN for {service_name}")
                yield {
                    "type": "error",
                    "text": f"{service_name} service temporarily unavailable",
                    "service": service_name,
                }
                continue

            # Select adapter
            adapter = (
                self.staff_adapter if service_name == "staff"
                else self.policy_adapter
            )

            # Call service
            try:
                ctx = {
                    **context,
                    "jwt_token": jwt_token,
                }
                async for event in adapter.call_streaming(question, ctx):
                    yield event
                await record_success(service_name)
            except Exception as e:
                await record_failure(service_name)
                error_event = await handle_adapter_error(e, service_name, context)
                yield error_event


async def health_check_services(orchestrator: ServiceOrchestrator) -> Dict[str, Any]:
    """Check health of all services.

    Args:
        orchestrator: ServiceOrchestrator instance

    Returns:
        {"staff": true/false, "policy": true/false}
    """
    health = {}
    for name, adapter in [
        ("staff", orchestrator.staff_adapter),
        ("policy", orchestrator.policy_adapter),
    ]:
        try:
            health[name] = await adapter.health_check()
        except Exception as e:
            logger.warning(f"Health check failed for {name}: {e}")
            health[name] = False
    return health
