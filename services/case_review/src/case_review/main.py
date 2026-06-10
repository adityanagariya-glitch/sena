from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from case_review.api.routes import router
from case_review.api.voice_routes import voice_router
from case_review.core.logging import configure_logging
from case_review.core.settings import settings


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
    app.include_router(voice_router)
    return app
