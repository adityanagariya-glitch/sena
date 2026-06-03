"""Gateway extensions: /route orchestration, service adapters, circuit breaking.

Performance design:
  • ONE shared, pooled httpx.AsyncClient is reused across every downstream call
    (connection keep-alive) instead of a fresh client/handshake per question.
  • "both" routing fans out to staff AND policy CONCURRENTLY and merges their
    SSE streams as events arrive — dual-service latency ≈ the slower of the two,
    not the sum.
  • An early "meta" event is emitted the moment routing is known, so the client
    paints a "routing → <service>" status before the model starts streaming.
"""
import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, List, Tuple

import httpx

from adapters import StaffAdapter, PolicyAdapter, handle_adapter_error
from router import route_query
from circuit_breaker import can_call, record_success, record_failure

logger = logging.getLogger(__name__)

# Sentinel marking a producer has finished, used by the stream merger.
_DONE = object()


class ServiceOrchestrator:
    """Manages service adapters, routing, and circuit breaking."""

    def __init__(
        self,
        staff_url: str = "http://localhost:8001",
        policy_url: str = "http://localhost:8000",
        jwt_secret: str = "sena-local-qa-secret-change-in-prod",
    ):
        """Initialize orchestrator with service URLs and a shared pooled client."""
        # Shared keep-alive pool — downstream calls reuse connections.
        # Timeout: 60s total (staff agent loop can take 10-15s); connect is stricter.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=5.0, read=30.0),
            limits=httpx.Limits(max_keepalive_connections=64, max_connections=128,
                                keepalive_expiry=30.0),
        )
        self.staff_adapter = StaffAdapter("staff", staff_url, jwt_secret, client=self._client)
        self.policy_adapter = PolicyAdapter("policy", policy_url, jwt_secret, client=self._client)
        self.jwt_secret = jwt_secret

    async def aclose(self) -> None:
        """Close the shared client (call on app shutdown)."""
        await self._client.aclose()

    def _adapter_for(self, service_name: str):
        return self.staff_adapter if service_name == "staff" else self.policy_adapter

    async def _stream_one(
        self, service_name: str, question: str, ctx: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream one service, recording circuit-breaker success/failure."""
        adapter = self._adapter_for(service_name)
        try:
            async for event in adapter.call_streaming(question, ctx):
                yield event
            await record_success(service_name)
        except Exception as e:
            await record_failure(service_name)
            yield await handle_adapter_error(e, service_name, ctx)

    async def _merge_streams(
        self, services: List[str], question: str, ctx: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Run multiple service streams CONCURRENTLY, yielding events as they land.

        Each event is tagged with its source `service` so the client can label
        which backend ("staff" / "policy") produced it. Total latency ≈ the
        slowest single stream rather than the sum of both.
        """
        queue: asyncio.Queue = asyncio.Queue()

        async def producer(svc: str):
            try:
                async for event in self._stream_one(svc, question, ctx):
                    event.setdefault("service", svc)
                    await queue.put(event)
            finally:
                await queue.put(_DONE)

        tasks = [asyncio.create_task(producer(svc)) for svc in services]
        remaining = len(tasks)
        try:
            while remaining:
                item = await queue.get()
                if item is _DONE:
                    remaining -= 1
                    continue
                yield item
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()

    async def route_and_stream(
        self,
        question: str,
        jwt_token: str,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Route a question and stream the response from the chosen service(s)."""
        # The gateway is a pass-through: the inbound Bearer token is forwarded to
        # the downstream service unchanged (no minting/exchange/refresh), so there
        # is nothing to decode or cache here. Each service validates the token.

        # Route (chip category → instant; else cached/threaded Bedrock classify).
        routing = await route_query(question, context)
        logger.info(f"Query routed to: {routing['target_services']} ({routing['routing_reason']})")

        effective_question = routing.get("question", question)

        # Early feedback — client can paint the routing status immediately.
        yield {
            "type": "meta",
            "routing": routing,
            "session_id": context.get("session_id"),
        }

        targets: List[str] = routing["target_services"]
        if not targets:
            yield {
                "type": "token",
                "text": "This question is out of scope — I can only help with staff or policy questions.",
            }
            yield {"type": "done"}
            return

        ctx = {**context, "jwt_token": jwt_token}

        # Filter by circuit breaker; report any open breakers up front.
        callable_targets: List[str] = []
        for service_name in targets:
            if await can_call(service_name):
                callable_targets.append(service_name)
            else:
                logger.warning(f"Circuit breaker OPEN for {service_name}")
                yield {
                    "type": "error",
                    "text": f"{service_name} service temporarily unavailable",
                    "service": service_name,
                }

        if not callable_targets:
            yield {"type": "done"}
            return

        if len(callable_targets) == 1:
            # Single service — stream straight through (no merge overhead).
            async for event in self._stream_one(callable_targets[0], effective_question, ctx):
                yield event
        else:
            # Multiple services ("both") — fan out concurrently and merge.
            async for event in self._merge_streams(callable_targets, effective_question, ctx):
                yield event

        yield {"type": "done"}


async def health_check_services(orchestrator: ServiceOrchestrator) -> Dict[str, Any]:
    """Check health of all services CONCURRENTLY.

    Args:
        orchestrator: ServiceOrchestrator instance

    Returns:
        {"staff": true/false, "policy": true/false}
    """
    names = ["staff", "policy"]
    adapters = [orchestrator.staff_adapter, orchestrator.policy_adapter]
    results = await asyncio.gather(
        *(a.health_check() for a in adapters), return_exceptions=True
    )
    health: Dict[str, Any] = {}
    for name, res in zip(names, results):
        health[name] = res if isinstance(res, bool) else False
    return health
