"""
Standalone Gemini Live demo server — continuous-streaming pipeline, no DB/Redis/auth.

Run:
    cd sena-ai
    source ../.venv/Scripts/activate
    uvicorn demo_live_server:app --reload --port 8082

Then open: http://localhost:8082
"""
import asyncio
import json
import logging
import os
import uuid
import warnings

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pathlib import Path
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_KEY = os.getenv("SENA_AI_GEMINI_API_KEY")
MODEL   = os.getenv("SENA_AI_GEMINI_LIVE_MODEL_ID", "gemini-3.1-flash-live-preview")

SYSTEM_PROMPT = (
    "You are a warm, friendly voice assistant helping an Australian NDIS participant "
    "fill in their personal details form. "
    "When the user first speaks (even just 'hello' or any sound), greet them warmly: "
    "'Hi there! I am your SENA onboarding assistant. I will help you fill in your "
    "personal details today. Can I start with your first name?' "
    "Then ask for one or two details at a time. Use Australian English. Be patient, "
    "warm, and conversational. Keep responses short."
)

# In-memory sessions
_sessions: dict[str, dict] = {}

app = FastAPI(title="SENA Gemini Live Demo")


@app.get("/")
async def client():
    return FileResponse(Path(__file__).parent / "demo_client.html")


@app.post("/session")
async def create_session():
    sid = str(uuid.uuid4())
    _sessions[sid] = {}
    logger.info("session_created id=%s", sid)
    return {"session_id": sid}


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    fields = _sessions.get(session_id)
    if fields is None:
        return {"error": "not found"}
    return {"session_id": session_id, "fields": fields}


@app.websocket("/live/{session_id}")
async def live_audio(websocket: WebSocket, session_id: str):
    """
    Continuous audio bridge: browser mic → Gemini Live → browser speaker.

    Client → Server:  Binary   — PCM16 16 kHz mono chunks streamed continuously
                      Text JSON {"type":"end_session"}
    Server → Client:  Binary   — PCM16 24 kHz mono chunks from Gemini
                      Text JSON {"type":"turn_start"|"turn_complete"|"error", ...}

    VAD-driven: no explicit audio_stream_end — Gemini auto-detects turn boundaries.
    """
    await websocket.accept()

    if session_id not in _sessions:
        await websocket.send_text(json.dumps({"type": "error", "message": "Invalid session"}))
        await websocket.close(code=4004)
        return

    logger.info("live_connect session=%s model=%s", session_id, MODEL)
    client = genai.Client(api_key=API_KEY)

    # Explicit multi-turn config:
    #  - automatic_activity_detection (VAD) enabled so Gemini auto-detects turn boundaries
    #  - session_resumption handle allows the session to survive beyond Gemini's default
    #    short-session heuristic (critical for conversational multi-turn)
    #  - output_audio_transcription so we can log what Gemini actually says (debugging)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_PROMPT)],
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                prefix_padding_ms=200,
                silence_duration_ms=800,
            ),
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
            turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
        ),
        session_resumption=types.SessionResumptionConfig(handle=None),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
    )

    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            logger.info("gemini_connected session=%s", session_id)

            async def _browser_to_gemini():
                """Forward browser mic audio → Gemini continuously. Returns when browser disconnects."""
                total_chunks = 0
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            return
                        raw = msg.get("bytes")
                        if raw:
                            await session.send_realtime_input(
                                audio=types.Blob(data=raw, mime_type="audio/pcm;rate=16000")
                            )
                            total_chunks += 1
                            if total_chunks % 50 == 0:
                                logger.info("streaming chunks=%d session=%s", total_chunks, session_id)
                        elif msg.get("text"):
                            data = json.loads(msg["text"])
                            if data.get("type") == "end_session":
                                logger.info("end_session chunks=%d session=%s", total_chunks, session_id)
                                return
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception:
                    logger.exception("browser_to_gemini_error")

            async def _gemini_to_browser():
                """Forward Gemini audio → browser. Auto-restarts receive loop if it exits."""
                chunk_count = 0
                turn_started = False
                loop_iter = 0
                try:
                    while True:
                        loop_iter += 1
                        logger.info("g2b_receive_loop_start iter=%d session=%s", loop_iter, session_id)
                        async for msg in session.receive():
                            # Transcription diagnostics — shows what Gemini hears / says
                            if msg.server_content and msg.server_content.input_transcription:
                                txt = msg.server_content.input_transcription.text
                                if txt:
                                    logger.info("USER_SAID: %r session=%s", txt, session_id)
                            if msg.server_content and msg.server_content.output_transcription:
                                txt = msg.server_content.output_transcription.text
                                if txt:
                                    logger.info("GEMINI_SAID: %r session=%s", txt, session_id)
                            # GoAway warnings (Gemini signalling it will close soon)
                            if msg.go_away:
                                logger.warning("GO_AWAY received time_left=%s session=%s",
                                               msg.go_away.time_left, session_id)
                            if msg.server_content and msg.server_content.model_turn:
                                for part in msg.server_content.model_turn.parts:
                                    if part.inline_data:
                                        if not turn_started:
                                            await websocket.send_text(json.dumps({"type": "turn_start"}))
                                            turn_started = True
                                            logger.info("turn_start session=%s", session_id)
                                        await websocket.send_bytes(part.inline_data.data)
                                        chunk_count += 1
                            if msg.server_content and msg.server_content.interrupted:
                                logger.info("interrupted session=%s", session_id)
                                await websocket.send_text(json.dumps({"type": "interrupted"}))
                                turn_started = False
                                chunk_count = 0
                            if msg.server_content and msg.server_content.turn_complete:
                                logger.info("turn_complete chunks=%d session=%s", chunk_count, session_id)
                                await websocket.send_text(json.dumps({"type": "turn_complete"}))
                                chunk_count = 0
                                turn_started = False
                        # Receive iterator exited — with google-genai SDK, `session.receive()`
                        # completes at end of a "batch" but the underlying WS session is still open.
                        # Loop back and call receive() again for the next turn.
                        logger.warning("g2b_receive_iterator_ended iter=%d (re-entering) session=%s",
                                       loop_iter, session_id)
                        await asyncio.sleep(0.01)   # yield to event loop
                        continue
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception:
                    logger.exception("gemini_to_browser_error")

            # Lifecycle: session stays alive until the BROWSER disconnects.
            # g2b dying (Gemini closing its side) does NOT end the session —
            # this lets the browser reconnect / send more audio without tearing down.
            b2g = asyncio.create_task(_browser_to_gemini())
            g2b = asyncio.create_task(_gemini_to_browser())
            try:
                await b2g          # blocks until browser disconnects
            finally:
                g2b.cancel()
                await asyncio.gather(g2b, return_exceptions=True)

    except Exception:
        logger.exception("live_session_error session=%s", session_id)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": "Gemini connection failed"}))
        except Exception:
            pass

    try:
        await websocket.close()
    except Exception:
        pass
    logger.info("live_done session=%s", session_id)
