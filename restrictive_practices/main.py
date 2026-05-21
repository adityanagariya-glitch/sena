import logging
import os
import traceback
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from api.routes import _require_auth, router
from api.voice_routes import set_voice_repo, voice_router
from config import settings
from db.session import create_tables
from voice.state_repo import VoiceStateRepo

_DEMO_HTML = Path(__file__).parent / "demo_ui.html"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="NDIS Restrictive Practice Detection",
        description="AI pipeline to detect regulated restrictive practices from NDIS case notes.",
        version="0.1.0",
    )

    demo_host = os.getenv("SENA_AI_DEMO_HOST", "")
    origins = [demo_host] if demo_host else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.include_router(voice_router)

    @app.get("/demo", include_in_schema=False, dependencies=[Depends(_require_auth)])
    async def demo_ui() -> FileResponse:
        return FileResponse(_DEMO_HTML, media_type="text/html")

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        tb = traceback.format_exc()
        logger.error("Unhandled exception on %s %s:\n%s", request.method, request.url.path, tb)
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}", "traceback": tb},
        )

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("Creating DB tables...")
        try:
            await create_tables()
            logger.info("DB tables ready.")
        except Exception as exc:
            logger.warning(
                "DB not reachable at startup — start PostgreSQL before using pipeline endpoints. (%s)",
                exc,
            )
        try:
            redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
            await redis_client.ping()
            repo = VoiceStateRepo(redis_client)
            set_voice_repo(repo)
            logger.info("Voice Redis connected: %s", settings.redis_url)
        except Exception as exc:
            logger.warning(
                "Redis not reachable at startup — voice endpoints unavailable. (%s)", exc
            )
        logger.info("Startup complete.")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        from api.voice_routes import _repo as voice_repo_instance
        try:
            if voice_repo_instance is not None:
                await voice_repo_instance._r.aclose()
        except Exception:
            pass

    return app


app = create_app()
