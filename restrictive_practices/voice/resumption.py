"""Session resumption service for the case-note voice assistant."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from voice.state_repo import VoiceStateRepo

log = structlog.get_logger(__name__)


async def issue_handle(
    repo: "VoiceStateRepo",
    session_id: str,
    ttl_sec: int,
) -> str:
    handle = str(uuid.uuid4())
    await repo.save_resumption_handle(handle, session_id, ttl_sec=ttl_sec)
    log.debug("resumption_handle_issued session=%s handle=%.8s…", session_id, handle)
    return handle


async def redeem_handle(
    repo: "VoiceStateRepo",
    handle: str,
    expected_session_id: str,
) -> bool:
    stored = await repo.redeem_resumption_handle(handle)
    if stored is None:
        log.debug("resumption_handle_missing handle=%.8s…", handle)
        return False
    if stored != expected_session_id:
        log.warning(
            "resumption_handle_mismatch handle=%.8s… expected=%s stored=%s",
            handle,
            expected_session_id,
            stored,
        )
        return False
    log.info("resumption_handle_redeemed session=%s handle=%.8s…", expected_session_id, handle)
    return True


def build_replay_context(transcript: list[dict], last_n: int) -> str:
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
