"""
Session resumption service — Phase E.

Thin layer over the Redis primitives in FormStateRepo:
  - issue_handle  : generate opaque UUID4 handle, store with TTL
  - redeem_handle : atomic single-use validation (GETDEL)
  - build_replay_context : format last N transcript turns for Gemini injection

Handles are opaque (UUID4, not session_id). Only first 8 chars are ever logged
to prevent handle leak via log aggregation.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from state_repo import FormStateRepo

log = structlog.get_logger(__name__)


async def issue_handle(
    repo: FormStateRepo,
    session_id: str,
    ttl_sec: int,
) -> str:
    """
    Generate a UUID4 resumption handle, store it in Redis with TTL, return it.
    The handle is NOT the session_id — it's an opaque token the client stores.
    """
    handle = str(uuid.uuid4())
    await repo.save_resumption_handle(handle, session_id, ttl_sec=ttl_sec)
    log.debug("resumption_handle_issued session=%s handle=%.8s…", session_id, handle)
    return handle


async def redeem_handle(
    repo: FormStateRepo,
    handle: str,
    expected_session_id: str,
) -> bool:
    """
    Atomically validate and consume a resumption handle (single-use via GETDEL).

    Returns True only if:
      - handle exists in Redis (not expired)
      - stored session_id matches expected_session_id
      - handle has been deleted (consumed — cannot be reused)

    Returns False on expiry, mismatch, or double-redeem.
    """
    stored = await repo.redeem_resumption_handle(handle)
    if stored is None:
        log.debug("resumption_handle_missing handle=%.8s…", handle)
        return False
    if stored != expected_session_id:
        log.warning(
            "resumption_handle_mismatch handle=%.8s… expected_session=%s stored_session=%s",
            handle,
            expected_session_id,
            stored,
        )
        return False
    log.info("resumption_handle_redeemed session=%s handle=%.8s…", expected_session_id, handle)
    return True


def build_replay_context(transcript: list[dict], last_n: int) -> str:
    """
    Format the last N transcript entries as a [RESUME] text turn for Gemini injection.

    Returns empty string when transcript is empty or all entries have no text.
    The injected text cues the model to continue naturally without reintroducing itself.

    Example output:
        [RESUME] last turns: user="My name is Jane"; agent="Got it, Jane. ...".
        Continue from where you left off.
    """
    if not transcript or last_n <= 0:
        return ""

    window = transcript[-last_n:]
    parts: list[str] = []
    for entry in window:
        speaker = entry.get("speaker", "")
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        label = "user" if speaker == "user" else "agent"
        parts.append(f'{label}="{text}"')

    if not parts:
        return ""

    turns_str = "; ".join(parts)
    return f"[RESUME] last turns: {turns_str}. Continue from where you left off."
