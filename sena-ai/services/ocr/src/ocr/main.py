"""OCR Service — FastAPI application factory.

This is the reference service scaffold. Every future Sena AI service
(RAG, voice, risk flagging, etc.) follows this same pattern.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from sena_common.config.settings import Settings
from sena_common.db.session import close_engine, init_engine
from sena_common.middleware.error_handler import (
    ResourceNotFoundError,
    TenantIsolationError,
    http_exception_handler,
    resource_not_found_handler,
    tenant_isolation_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from sena_common.middleware.request_id import RequestIDMiddleware
from sena_common.middleware.tenant_context import HeaderTenantResolver, TenantMiddleware

from ocr.api.routes import router as ocr_router
from ocr.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown events."""
    settings = get_settings()
    init_engine(settings.database_url)
    yield
    await close_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Sena OCR Service",
        version=settings.service_version,
        docs_url="/docs" if settings.environment == "development" else None,
        lifespan=lifespan,
    )

    # -- Middleware (order matters: outermost first) --
    # Request ID must be outermost so all logs have correlation ID
    app.add_middleware(RequestIDMiddleware)
    # Tenant context must wrap all route handlers
    app.add_middleware(TenantMiddleware, resolver=HeaderTenantResolver())

    # -- Exception handlers --
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(TenantIsolationError, tenant_isolation_handler)
    app.add_exception_handler(ResourceNotFoundError, resource_not_found_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # -- Routers --
    app.include_router(ocr_router, prefix="/v1/ocr", tags=["OCR"])

    return app
