"""
Regression tests for GeminiLiveSession final-usage flush on session end.

Fix under test: when a voice session ends via `client_stop` (which cancels the
Gemini reader BEFORE the final `turn_complete`), any accumulated-but-unemitted
token usage must be flushed exactly once via `emit_usage(...)`.

Proves:
  (a) pending usage IS flushed on session end (delta = cum - emitted > 0),
  (b) it is NOT double-counted when a `turn_complete` already emitted the last
      turn (cum == emitted → delta 0 → no emit_usage call),
  (c) the session-end teardown path (run()'s finally block) actually INVOKES
      the helper — this is the wiring the bug breaks; test (c) is RED until the
      fix lands.

Strategy:
  - (a)/(b) call `_flush_pending_usage(...)` directly with primed counters and
    patch `emit_usage` where it is USED (module-level import in gemini_live),
    not where it is defined.
  - (c) drive `run()` with genai.Client + the bridge coroutines mocked so the
    session ends immediately, and spy on `_flush_pending_usage`.

Helper is SYNC (`def _flush_pending_usage(self, *, reason: str)`) — emit_usage
is a sync fire-and-forget, so the helper is a plain method called without await
from run()'s finally. Attr names confirmed against the landed diff. Test style
matches `test_gemini_live.py`:
unittest.mock only (pytest-mock/`mocker` is NOT a project dep), AsyncMock
websocket, FormStateRepo over fake_redis, asyncio_mode="auto" + explicit
@pytest.mark.asyncio.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice.state_repo import FormStateRepo
from voice.config import VoiceEngineConfig
from voice.gemini_live import GeminiLiveSession

# Patch emit_usage where it is USED (imported at gemini_live.py:52), NOT where
# it is defined in usage_logger. Covers the real import and the
# ImportError fallback stub — both bind the name in this module's namespace.
EMIT_USAGE_TARGET = "voice.gemini_live.emit_usage"


def _make_session(repo: FormStateRepo, session_id: str = "sid-1") -> GeminiLiveSession:
    ws = MagicMock()
    ws.send_text = AsyncMock()
    cfg = VoiceEngineConfig(
        gemini_api_key="test-key",
        gemini_live_model_id="gemini-3.1-flash-live-preview",
    )
    return GeminiLiveSession(
        websocket=ws,
        session_id=session_id,
        system_instruction="test",
        repo=repo,
        config=cfg,
    )


# ── (a) pending usage IS flushed + idempotent ───────────────────────────────


@pytest.mark.asyncio
async def test_flush_pending_usage_emits_once_when_delta_outstanding(
    fake_redis,
) -> None:
    """Session end with unemitted cumulative usage → emit_usage called once
    with the outstanding delta; a second flush is a no-op (idempotent)."""
    repo = FormStateRepo(fake_redis)
    session = _make_session(repo)

    with patch(EMIT_USAGE_TARGET) as spy:
        # Cumulative usage the last turn_complete never got to emit.
        # ── CONFIRM these attr names against the fix ──────────────────────
        session._usage_cum_prompt = 120
        session._usage_cum_response = 80
        session._usage_cum_cached = 0
        session._usage_cum_prompt_audio = 100
        session._usage_cum_response_audio = 60
        session._usage_emitted_prompt = 0
        session._usage_emitted_response = 0
        session._usage_emitted_cached = 0
        session._usage_emitted_prompt_audio = 0
        session._usage_emitted_response_audio = 0
        # ──────────────────────────────────────────────────────────────────

        session._flush_pending_usage(reason="client_stop")

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert kwargs["prompt_tokens"] == 120
        assert kwargs["response_tokens"] == 80
        assert kwargs["prompt_audio_tokens"] == 100
        assert kwargs["response_audio_tokens"] == 60
        assert kwargs["session_id"] == "sid-1"

        # Idempotency: emitted counters advanced to cumulative → a second flush
        # (e.g. finally-block after client_stop already flushed) does nothing.
        spy.reset_mock()
        session._flush_pending_usage(reason="finally")
        spy.assert_not_called()


# ── (b) NOT double-counted when turn_complete already emitted ────────────────


@pytest.mark.asyncio
async def test_flush_pending_usage_noop_when_turn_complete_already_emitted(
    fake_redis,
) -> None:
    """turn_complete already emitted the last turn (emitted == cumulative) →
    final flush must NOT double-count.

    Relies on chunk_count / _tool_calls_in_turn being 0 (defaults from
    __init__) so the emit guard fails and no zero-token row is written."""
    repo = FormStateRepo(fake_redis)
    session = _make_session(repo)

    with patch(EMIT_USAGE_TARGET) as spy:
        # ── CONFIRM these attr names against the fix ──────────────────────
        session._usage_cum_prompt = 200
        session._usage_cum_response = 150
        session._usage_cum_cached = 0
        session._usage_cum_prompt_audio = 0
        session._usage_cum_response_audio = 0
        session._usage_emitted_prompt = 200
        session._usage_emitted_response = 150
        session._usage_emitted_cached = 0
        session._usage_emitted_prompt_audio = 0
        session._usage_emitted_response_audio = 0
        # ──────────────────────────────────────────────────────────────────

        session._flush_pending_usage(reason="client_stop")

        spy.assert_not_called()


# ── (c) the teardown path actually INVOKES the flush (RED until the fix) ─────


@pytest.mark.asyncio
async def test_session_end_invokes_flush_pending_usage(fake_redis) -> None:
    """run()'s finally block (reached on client_stop / disconnect) must call
    _flush_pending_usage exactly once.

    EXPECTED TO FAIL until the fix wires the helper into run()'s teardown.
    Drives run() with genai.Client + the bridge coroutines stubbed so the
    session ends immediately, then spies on the helper itself.
    """
    repo = FormStateRepo(fake_redis)
    session = _make_session(repo)

    # Fake async context-manager session yielded by client.aio.live.connect(...)
    fake_live = AsyncMock()
    connect_cm = MagicMock()
    connect_cm.__aenter__ = AsyncMock(return_value=fake_live)
    connect_cm.__aexit__ = AsyncMock(return_value=False)

    fake_client = MagicMock()
    fake_client.aio.live.connect = MagicMock(return_value=connect_cm)

    with (
        patch("voice.gemini_live.genai.Client", return_value=fake_client),
        # b2g returns immediately → simulates client_stop ending the bridge.
        patch.object(session, "_browser_to_gemini", new=AsyncMock(return_value=None)),
        patch.object(session, "_gemini_to_browser", new=AsyncMock(return_value=None)),
        patch.object(session, "_silence_monitor", new=AsyncMock(return_value=None)),
        # Helper is SYNC — MagicMock, not AsyncMock.
        patch.object(
            session, "_flush_pending_usage", new=MagicMock(return_value=None)
        ) as flush_spy,
    ):
        await session.run()

    flush_spy.assert_called_once()
