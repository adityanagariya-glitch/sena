from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from voice.api.routes import router
from voice.api.ws_routes import ws_router
from voice.core.logging import configure_logging
from voice.core.settings import settings
from voice.api.deps import ai_engine, shared_engine
from voice.models.db import Base

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    # Create voice's tables in the AI DB on startup (idempotent — only creates
    # tables that don't already exist). Mirrors case_review's self-init; wrapped so
    # a transient DB outage doesn't crash boot. The shared/platform DB is externally
    # managed — we never create tables there.
    try:
        async with ai_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Voice DB tables ready (ai-db).")
    except Exception as exc:
        logger.warning("Voice DB table creation skipped — ai-db not reachable (%s)", exc)
    yield
    await ai_engine.dispose()
    await shared_engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="SENA Voice Service - Flow B",
        version=settings.service_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.include_router(ws_router)
    return app
