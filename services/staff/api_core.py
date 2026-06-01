"""FastAPI app factory, lifespan management, and middleware setup.

Exports:
  - create_app() → FastAPI instance with full middleware chain
  - lifespan context manager for async startup/teardown
"""
import os
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure structured logging for the staff API."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Async context manager for app startup/teardown events."""
    logger.info("Staff API starting up")
    # Future: DB connections, cache initialization, etc.
    yield
    logger.info("Staff API shutting down")
    # Future: graceful cleanup


def create_app() -> FastAPI:
    """Factory function to create and configure the FastAPI application."""
    setup_logging()

    app = FastAPI(
        title="SENA Staff API",
        version="2.0.0",
        description="Staff service: auth, streaming queries, request context isolation",
        lifespan=lifespan,
    )

    # CORS: Allow all origins (configure per environment in production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app
