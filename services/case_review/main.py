from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from api.routes import router
from api.rp_routes import rp_router
from api.voice_routes import voice_router
from core.logging import configure_logging
from core.settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="SENA Case Note Review API",
        version=settings.service_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.include_router(rp_router)
    app.include_router(voice_router)

    # Browser voice demo harness (case_review voice dictation). Served
    # same-origin so its relative fetch + WS work without CORS. voice_demo.html
    # sits at the service root (services/case_review/) — two levels up from
    # this package module (src/case_review/main.py).
    @app.get("/demo", include_in_schema=False)
    async def voice_demo() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parents[2] / "voice_demo.html",
            media_type="text/html",
        )

    # Case note drafter manual test UI — served same-origin so fetch works without CORS.
    @app.get("/draft-demo", include_in_schema=False)
    async def draft_demo() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parents[2] / "draft_demo.html",
            media_type="text/html",
        )

    return app
