from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from onboarding.api.routes import router
from onboarding.api.ws_routes import ws_router
from onboarding.core.logging import configure_logging
from onboarding.core.settings import settings

# sena-ai/services/onboarding/   (main.py → onboarding → src → onboarding-service)
HARNESS_DIR = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="SENA Onboarding Voice API",
        version=settings.service_version,
        description=(
            "AI voice agent for NDIS participant onboarding. "
            "WebSocket protocol documented in docs/WS_PROTOCOL.md."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.include_router(ws_router)

    @app.get("/harness", include_in_schema=False)
    async def serve_harness() -> FileResponse:
        p = HARNESS_DIR / "test_harness.html"
        if not p.exists():
            raise HTTPException(404, "test_harness.html not found")
        return FileResponse(
            p,
            media_type="text/html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/harness/fixtures/{step_id}", include_in_schema=False)
    async def serve_fixture(step_id: str) -> FileResponse:
        # Prevent path traversal — only allow alnum + underscore
        if not step_id.replace("_", "").isalnum():
            raise HTTPException(400, "invalid step_id")
        p = HARNESS_DIR / "fixtures" / f"schema_{step_id}.json"
        if not p.exists():
            raise HTTPException(404, f"fixture not found: {step_id}")
        return FileResponse(p, media_type="application/json")

    return app
