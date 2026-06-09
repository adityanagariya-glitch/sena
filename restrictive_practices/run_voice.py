"""Voice-only boot — mounts ONLY the Gemini Live voice route (no langgraph/Bedrock pipeline).

Dev/demo runner. `main.py` drags in the full restrictive-practice analysis pipeline
(langgraph + Bedrock), which the voice assistant does not need and which is not the
target shape for case_review. This mirrors main.py's voice wiring verbatim, nothing more.

Run:  uvicorn run_voice:app --host 127.0.0.1 --port 8086
Then open  http://127.0.0.1:8086/voice-demo  and speak.
"""

import logging
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.voice_routes import set_voice_repo, voice_router
from config import settings
from voice.state_repo import VoiceStateRepo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_VOICE_DEMO_HTML = Path(__file__).parent / "voice_demo.html"


def create_app() -> FastAPI:
    app = FastAPI(title="SENA Voice (case-note) — voice-only boot")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(voice_router)

    @app.get("/voice-demo", include_in_schema=False)
    async def voice_demo_ui() -> FileResponse:
        return FileResponse(_VOICE_DEMO_HTML, media_type="text/html")

    @app.on_event("startup")
    async def _startup() -> None:
        # protocol=2 (RESP2): the native Windows Redis 5.0 on this box predates the
        # RESP3 HELLO handshake redis-py sends by default → "unknown command HELLO".
        client = aioredis.from_url(settings.redis_url, decode_responses=False, protocol=2)
        await client.ping()
        set_voice_repo(VoiceStateRepo(client))
        logger.info("Voice Redis connected: %s", settings.redis_url)

    return app


app = create_app()
