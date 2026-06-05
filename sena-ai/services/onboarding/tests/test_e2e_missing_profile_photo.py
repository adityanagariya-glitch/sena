"""E2E test for the missing-profile-photo blocker scenario.

This is the spec's acceptance-criteria scenario from §15: the participant
says 'submit' but mobile detects the profile picture is empty and returns
a blocker. The voice agent must receive the verbatim reason so it can
read it to the user.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from onboarding.services.mobile_bridge import MobileBridge
from onboarding.services.tools import ToolDispatcher


class _ScriptedWS:
    """A scripted fake of the mobile WS endpoint.

    When the backend dispatcher sends a `tool_request` over the WS, this
    fake parses the request and resolves the bridge with the canned
    response keyed by tool name. Mimics how the Flutter app would respond.
    """

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.bridge: MobileBridge | None = None

    async def send_text(self, payload: str) -> None:
        msg = json.loads(payload)
        request_id = msg["request_id"]
        tool = msg["tool"]
        # Resolve on the next loop tick so the awaiting dispatch() coroutine
        # has a chance to register its future first.
        if self.bridge is not None and tool in self.responses:
            asyncio.get_event_loop().call_soon(
                self.bridge.resolve,
                request_id,
                self.responses[tool],
            )


@pytest.mark.asyncio
async def test_submit_with_missing_profile_photo_returns_blocker() -> None:
    ws = _ScriptedWS(
        responses={
            "submit_step": {
                "ok": False,
                "blockers": [
                    {
                        "path": "basics.profile_picture",
                        "label": "Profile Photo",
                        "reason": "Profile photo is required.",
                    }
                ],
            }
        }
    )
    bridge = MobileBridge(ws, timeout_sec=1.0)
    ws.bridge = bridge
    dispatcher = ToolDispatcher(bridge=bridge)

    result = await dispatcher.dispatch(
        "submit_step",
        {"confirmation_transcript": "I'm done, submit it."},
    )

    assert result["ok"] is False
    assert "blockers" in result
    blockers = result["blockers"]
    assert len(blockers) == 1
    blocker = blockers[0]
    assert blocker["path"] == "basics.profile_picture"
    assert blocker["label"] == "Profile Photo"
    assert "Profile photo" in blocker["reason"]


@pytest.mark.asyncio
async def test_submit_step_step_completed_stays_false_on_blocker() -> None:
    """The dispatcher's step_completed flag must NOT flip when submit_step
    returns blockers. gemini_live.py uses this flag to end the session;
    a false flip would close the WS while the user still needs to fix
    the profile photo."""
    ws = _ScriptedWS(
        responses={
            "submit_step": {
                "ok": False,
                "blockers": [
                    {
                        "path": "basics.profile_picture",
                        "label": "Profile Photo",
                        "reason": "Required.",
                    },
                ],
            }
        }
    )
    bridge = MobileBridge(ws, timeout_sec=1.0)
    ws.bridge = bridge
    dispatcher = ToolDispatcher(bridge=bridge)

    await dispatcher.dispatch("submit_step", {"confirmation_transcript": "submit"})

    assert dispatcher.step_completed is False, (
        "step_completed must remain False so the session stays open for the fix"
    )


@pytest.mark.asyncio
async def test_submit_step_step_completed_flips_on_clean_submit() -> None:
    """Sanity check: a clean {ok: true} submission DOES flip step_completed."""
    ws = _ScriptedWS(responses={"submit_step": {"ok": True}})
    bridge = MobileBridge(ws, timeout_sec=1.0)
    ws.bridge = bridge
    dispatcher = ToolDispatcher(bridge=bridge)

    await dispatcher.dispatch("submit_step", {"confirmation_transcript": "all done"})

    assert dispatcher.step_completed is True
