"""Forwards Gemini tool calls to the mobile app over WS and awaits the
mobile-authoritative verdict.

Mobile owns validation; the backend is a relay. One bridge per session.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)


class _WSLike(Protocol):
    async def send_text(self, data: str) -> None: ...


class MobileBridge:
    def __init__(self, ws: _WSLike, *, timeout_sec: float = 5.0) -> None:
        self._ws = ws
        self._timeout = timeout_sec
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def dispatch(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        try:
            await self._ws.send_text(json.dumps({
                "type": "tool_request",
                "request_id": request_id,
                "tool": tool,
                "args": args,
            }))
            return await asyncio.wait_for(fut, timeout=self._timeout)
        except TimeoutError:
            log.warning("mobile_bridge_timeout", tool=tool, request_id=request_id)
            return {"ok": False, "reason": "Validation timed out", "code": "mobile_timeout"}
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, result: dict[str, Any]) -> None:
        fut = self._pending.get(request_id)
        if fut and not fut.done():
            fut.set_result(result)
