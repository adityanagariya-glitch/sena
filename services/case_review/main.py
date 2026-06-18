from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.routes import router
from api.rp_routes import rp_router
from api.voice_routes import voice_router
from core.logging import configure_logging
from core.settings import settings

logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    """Apply Alembic migrations to head.

    Migrations 0001-0002 are idempotent (CREATE TABLE / ADD COLUMN ... IF NOT
    EXISTS) and 0003-0004 are idempotent reconcilers, so this checks every table
    and creates only what's missing — safe to run on every startup.

    Run in a worker thread (see lifespan): Alembic's env.py uses asyncio.run(),
    which cannot be called from within the already-running lifespan event loop.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig

    ini_path = Path(__file__).resolve().parent / "alembic.ini"
    cfg = AlembicConfig(str(ini_path))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    logger.info("applying database migrations (alembic upgrade head)...")
    await asyncio.to_thread(_run_migrations)
    logger.info("database migrations applied; tables verified")
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
    # Demo UIs (the Streamlit-embedded draft_demo.html) call the API cross-origin.
    # /draft has no auth, so a permissive CORS policy is fine; /evaluate keeps its
    # own Basic-auth dependency regardless.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(rp_router)
    app.include_router(voice_router)

    # Browser voice demo harness (case_review voice dictation). Served
    # same-origin so its relative fetch + WS work without CORS. voice_demo.html
    # sits alongside main.py at services/case_review/.
    @app.get("/demo", include_in_schema=False)
    async def voice_demo() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parent / "voice_demo.html",
            media_type="text/html",
        )

    # Case note drafter manual test UI — served same-origin so fetch works without CORS.
    @app.get("/draft-demo", include_in_schema=False)
    async def draft_demo() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parent / "draft_demo.html",
            media_type="text/html",
        )

    return app
