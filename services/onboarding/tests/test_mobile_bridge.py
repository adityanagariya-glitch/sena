from __future__ import annotations

import asyncio
import json

import pytest

from voice.mobile_bridge import MobileBridge


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


@pytest.mark.asyncio
async def test_dispatch_round_trip_happy_path() -> None:
    ws = _FakeWS()
    bridge = MobileBridge(ws, timeout_sec=1.0)

    async def respond_after_send() -> None:
        await asyncio.sleep(0)
        request_id = ws.sent[-1]["request_id"]
        bridge.resolve(request_id, {"ok": True})

    task = asyncio.create_task(respond_after_send())
    result = await bridge.dispatch(
        "update_field", {"section": "basics", "field": "phone", "value": "0412345678"}
    )
    await task

    assert result == {"ok": True}
    sent = ws.sent[-1]
    assert sent["type"] == "tool_request"
    assert sent["tool"] == "update_field"
    assert sent["args"]["value"] == "0412345678"
    assert "request_id" in sent


@pytest.mark.asyncio
async def test_dispatch_timeout_returns_validation_timeout() -> None:
    ws = _FakeWS()
    bridge = MobileBridge(ws, timeout_sec=0.05)
    result = await bridge.dispatch("update_field", {"section": "x", "field": "y", "value": "z"})
    assert result == {"ok": False, "reason": "Validation timed out", "code": "mobile_timeout"}


@pytest.mark.asyncio
async def test_resolve_unknown_request_id_is_silently_ignored() -> None:
    ws = _FakeWS()
    bridge = MobileBridge(ws, timeout_sec=1.0)
    bridge.resolve("never-was-here", {"ok": True})  # must not raise


@pytest.mark.asyncio
async def test_dispatch_concurrent_requests_get_distinct_ids() -> None:
    ws = _FakeWS()
    bridge = MobileBridge(ws, timeout_sec=1.0)

    async def driver() -> None:
        await asyncio.sleep(0)
        ids = [m["request_id"] for m in ws.sent]
        for rid in ids:
            bridge.resolve(rid, {"ok": True})

    task = asyncio.create_task(driver())
    results = await asyncio.gather(
        bridge.dispatch("update_field", {"section": "a", "field": "b", "value": "c"}),
        bridge.dispatch("update_field", {"section": "a", "field": "d", "value": "e"}),
    )
    await task
    assert all(r == {"ok": True} for r in results)
    sent_ids = {m["request_id"] for m in ws.sent}
    assert len(sent_ids) == 2
