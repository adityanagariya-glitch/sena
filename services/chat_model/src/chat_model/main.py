from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from chat_model.api import routes
from chat_model.api.deps import (
    initialize_chat_service,
    initialize_redis_client,
    shutdown_redis_client,
    initialize_db_engine,
    shutdown_db_engine,
)
from chat_model.core.settings import settings
from chat_model.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app lifecycle: init singletons on startup, cleanup on shutdown."""
    # Startup
    configure_logging(settings.log_level)
    await initialize_db_engine()
    redis_client = await initialize_redis_client()
    await initialize_chat_service(redis_client)

    yield

    # Shutdown
    await shutdown_redis_client()
    await shutdown_db_engine()


def create_app() -> FastAPI:
    """Create FastAPI application with auth, rate limiting, and singleton services."""
    app = FastAPI(
        title="Chat Model Service",
        description="AI chatbot service with langchain and Gemini",
        lifespan=lifespan,
    )

    # CORS with allowlist (not *)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Tenant-ID", "X-User-ID", "X-User-Role"],
    )

    app.include_router(routes.router)

    return app
