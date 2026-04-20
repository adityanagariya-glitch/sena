from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from voice.api.routes import router
from voice.api.ws_routes import ws_router
from voice.core.logging import configure_logging
from voice.core.settings import settings
from voice.api.deps import ai_engine, shared_engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
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
