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
            result = await asyncio.wait_for(fut, timeout=self._timeout)
            self._log_tool_response(tool, request_id, args, result)
            return result
        except TimeoutError:
            log.warning("mobile_bridge_timeout", tool=tool, request_id=request_id)
            return {"ok": False, "reason": "Validation timed out", "code": "mobile_timeout"}
        finally:
            self._pending.pop(request_id, None)

    @staticmethod
    def _log_tool_response(
        tool: str, request_id: str, args: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """Emit one clean line per tool_response. Highlights Option D state
        payload structure when present so the operator can see exactly what
        Flutter shipped back per turn.

        `args` is the exact payload the agent sent to Flutter — logged on
        rejection so the operator can see WHAT was asked (e.g. did delete_row
        carry a row_index? was it the right one?).

        Logs three shapes:
          * `tool_response_state` — Option D engaged: result carries `state`
          * `tool_response_no_state` — ok=true but no state key (legacy /
            Flutter hasn't shipped Option D yet)
          * `tool_response_rejected` — ok=false (mobile rejected the call)
        """
        if not isinstance(result, dict):
            log.warning("tool_response_unexpected", tool=tool, request_id=request_id, result_type=type(result).__name__)
            return

        ok = result.get("ok")
        if ok is False:
            log.info(
                "tool_response_rejected",
                tool=tool,
                request_id=request_id,
                args=args,
                reason=result.get("reason"),
                code=result.get("code"),
            )
            return

        state = result.get("state")
        if not isinstance(state, dict):
            # ok=true but no `state` key — Option D not yet engaged on mobile.
            # During Phase 1 rollout this will be the dominant shape; flips
            # to `tool_response_state` once Flutter ships the matching half.
            log.info(
                "tool_response_no_state",
                tool=tool,
                request_id=request_id,
                ok=ok,
                hint="flutter has not shipped Option D state channel yet",
            )
            return

        # ─── Option D engaged — log full state payload ──────────────────
        visible_fields = state.get("visible_fields") or []
        filled = sum(
            1
            for f in visible_fields
            if isinstance(f, dict) and f.get("value") not in (None, "", [], {})
        )
        empty = len(visible_fields) - filled

        next_target = state.get("next_target")
        step = state.get("step") or {}
        prior_steps_obj = state.get("prior_steps") or {}
        prior_steps_keys = list(prior_steps_obj.keys())
        participant = state.get("participant") or {}

        # Per-screen view: section prefix of next_target.path; None when form
        # is complete (next_target null) — in which case all fields are filled
        # and the agent should call submit_step.
        next_path = (next_target or {}).get("path") or ""
        screen = next_path.split(".", 1)[0] if "." in next_path else next_path or None

        # Compact field map for human scanning — {"basics.full_name":"Aditya",...}.
        # Mirrors the {"ok":true,"state":{...}} shape Option D specifies so the
        # operator can see exactly what Flutter shipped this turn.
        field_values = {
            f.get("path"): f.get("value")
            for f in visible_fields
            if isinstance(f, dict) and f.get("path")
        }

        log.info(
            "tool_response_state",
            tool=tool,
            request_id=request_id,
            step_id=step.get("id"),
            step_number=step.get("number"),
            screen=screen,
            next_target=next_target,            # full object: {path,label,reason}
            last_rejection=state.get("last_rejection"),
            pending_confirmation=state.get("pending_confirmation"),
            participant=participant,
            visible_fields_total=len(visible_fields),
            visible_fields_filled=filled,
            visible_fields_empty=empty,
            field_values=field_values,           # path → value map for every visible field
            prior_steps=prior_steps_keys,
            prior_steps_data=prior_steps_obj,    # full cross-step summaries
            bootstrap_mode=state.get("bootstrap_mode"),
        )

    def resolve(self, request_id: str, result: dict[str, Any]) -> None:
        fut = self._pending.get(request_id)
        if fut and not fut.done():
            fut.set_result(result)
