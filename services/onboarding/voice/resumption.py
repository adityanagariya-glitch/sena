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

import re
import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from state_repo import FormStateRepo

# Vocalized hesitation sounds only — "um / uh / er / erm / err" and elongations.
# Never lexical content in English, so removing them cannot change meaning.
# Deliberately NOT stripping "ah / oh / hmm / mm / like / you know / well / so".
# Applied ONLY to the resume-replay text (the one text-token surface in this
# audio-native Live service); the stored/displayed transcript is left intact.
# NOTE: kept byte-identical with voice/services/transcribe_service.py and
# case_review/services/pipeline/transcription.py; these services are
# intentionally isolated (no shared import path), so this small pure helper is
# duplicated rather than shared.
_FILLER_RE = re.compile(r"\b(?:um+|uh+|erm+|err+|er+)\b", re.IGNORECASE)


def _strip_fillers(text: str) -> str:
    """Remove vocalized filler sounds from an ASR transcript (meaning-preserving)."""
    cleaned = _FILLER_RE.sub("", text)
    cleaned = re.sub(r",(?:\s*,)+", ",", cleaned)       # collapse commas orphaned by removal
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)  # drop space before punctuation
    cleaned = re.sub(r",\s*([.!?])", r"\1", cleaned)    # drop comma stranded before sentence end
    cleaned = re.sub(r"\s{2,}", " ", cleaned)           # collapse runs of whitespace
    cleaned = re.sub(r"^[\s,]+", "", cleaned)           # trim leading space/comma
    return cleaned.strip()

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
        text = _strip_fillers((entry.get("text") or "").strip())
        if not text:
            continue
        label = "user" if speaker == "user" else "agent"
        parts.append(f'{label}="{text}"')

    if not parts:
        return ""

    turns_str = "; ".join(parts)
    return f"[RESUME] last turns: {turns_str}. Continue from where you left off."
