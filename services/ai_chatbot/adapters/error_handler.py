"""Error handler: turn adapter exceptions into clean, user-facing messages.

Design: the error path must be FAST and RELIABLE. We deliberately do NOT call an
LLM to "explain" a failure — that would add 1-2s of latency and could fail again
(the original error may itself be a Bedrock/timeout problem). Instead we map the
exception type to a concise, friendly message deterministically (0ms, never
throws). Bedrock region/model details live in router.py / staff config, not here.
"""
import logging
import sys
import traceback
from typing import Dict, Any

import httpx

logger = logging.getLogger(__name__)

# Write the REAL error straight to the terminal (original stderr), bypassing any
# logging-level / handler config — so the operator always sees the true cause,
# even though the USER only ever sees the friendly premade message.
_TERMINAL = sys.__stderr__


def _log_real_error_to_terminal(error: Exception, service_name: str) -> None:
    """Print the actual exception + traceback to the terminal (guaranteed)."""
    try:
        print(
            f"[adapter-error] {service_name}: {type(error).__name__}: {error}",
            file=_TERMINAL, flush=True,
        )
        traceback.print_exception(type(error), error, error.__traceback__, file=_TERMINAL)
        _TERMINAL.flush()
    except Exception:
        pass  # logging must never raise


def _friendly_message(error: Exception, service_name: str) -> str:
    """Map an exception to a short, user-friendly explanation (deterministic)."""
    svc = "the staff service" if service_name == "staff" else "the policy service"

    # Connection problems — service down or unreachable.
    if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout)):
        return f"I couldn't reach {svc} right now. Please try again in a moment."

    # Timeouts — service is up but slow / stuck.
    if isinstance(error, (httpx.ReadTimeout, httpx.PoolTimeout, httpx.TimeoutException)):
        return f"{svc.capitalize()} took too long to respond. Please try again."

    # HTTP status errors from the downstream service.
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        if code in (401, 403):
            return "Your session looks invalid or expired. Please sign in again."
        if code == 404:
            return f"I couldn't find what you asked for in {svc}."
        if code == 429:
            return f"{svc.capitalize()} is busy right now. Please try again shortly."
        if 500 <= code < 600:
            return f"{svc.capitalize()} hit an internal error. Please try again."
        return f"{svc.capitalize()} returned an unexpected response ({code})."

    # Anything else — generic, safe fallback.
    return "Sorry, something went wrong handling your request. Please try again."


async def explain_error(
    error: Exception,
    context: Dict[str, Any],
    service_name: str = "service",
) -> str:
    """Return a user-friendly explanation for an error (deterministic, instant)."""
    return _friendly_message(error, service_name)


async def handle_adapter_error(
    error: Exception,
    service_name: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Convert an adapter error to a user-facing SSE event.

    Args:
        error: Exception from the adapter
        service_name: Name of the service that failed (staff, policy)
        context: Request context (unused; kept for signature compatibility)

    Returns:
        Event dict (type: error, text: friendly explanation)
    """
    # Operator sees the REAL error in the terminal...
    _log_real_error_to_terminal(error, service_name)
    logger.exception(f"Adapter error from {service_name}: {error}")

    # ...the user only ever sees the friendly, premade message (no token cost).
    return {
        "type": "error",
        "text": _friendly_message(error, service_name),
        "service": service_name,
        "error_class": type(error).__name__,
    }
