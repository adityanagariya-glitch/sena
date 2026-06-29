from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.routes import router  # ARCHIVED: not registered in active API
from api.rp_routes import rp_router  # ARCHIVED: not registered in active API
from api.voice_routes import voice_router
from api.unified_incident_routes import unified_router
from api.shift_analysis_routes import shift_analysis_router
from core.logging import configure_logging
from core.settings import settings

logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    """Apply Alembic migrations to head.

    Migrations 0001-0005 are idempotent (CREATE TABLE / ADD COLUMN IF NOT EXISTS).
    Safe to run on every startup — Alembic tracks applied revisions.

    Run in a worker thread: Alembic's env.py uses asyncio.run(), which cannot be
    called from within the already-running lifespan event loop.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig

    ini_path = Path(__file__).resolve().parent / "alembic.ini"
    cfg = AlembicConfig(str(ini_path))
    command.upgrade(cfg, "head")


async def _maybe_ingest_policies() -> None:
    """Ingest NDIS policy PDFs on first boot (when the chunk table is empty).

    Runs with LLM-assisted section detection (Haiku) for the most accurate
    parent-child chunking. Takes ~3-5 minutes on first boot while PDFs download
    and embed — subsequent starts skip this entirely (table already has data).

    This is a ONE-TIME operation. After the first successful ingest the table
    has rows and this function returns immediately on every future startup.
    """
    try:
        from sqlalchemy import func, select
        from db.session import AsyncSessionLocal
        from case_review.models.db import NDISPolicyChunk

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(func.count()).select_from(NDISPolicyChunk))
            chunk_count = result.scalar_one()

        if chunk_count > 0:
            logger.info("ndis_ingest: %d chunks already in DB — skipping ingest", chunk_count)
            return

        logger.info("ndis_ingest: table empty — starting first-boot policy ingest (LLM-assist)...")
        print("[startup] NDIS policy table empty — ingesting PDFs with LLM-assisted chunking...")
        print("[startup] This takes 3-5 minutes on first boot. Subsequent starts skip this.")

        # Import and run the ingest function (same as: python scripts/ingest_ndis_policies.py --llm-assist)
        import sys
        scripts_dir = Path(__file__).resolve().parent / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        from ingest_ndis_policies import main as _ingest_main
        await _ingest_main(llm_assist=True)

        logger.info("ndis_ingest: first-boot ingest complete")
        print("[startup] NDIS policy ingest complete.")

    except Exception as exc:
        # Ingest failure is non-fatal — the app starts, RAG just returns empty
        # until ingest is run manually: python scripts/ingest_ndis_policies.py
        logger.warning(
            "ndis_ingest: first-boot ingest failed (%s: %s) — "
            "run scripts/ingest_ndis_policies.py manually to populate the policy DB",
            type(exc).__name__,
            exc,
        )
        print(f"[startup] WARNING: policy ingest failed ({type(exc).__name__}). "
              "Run: python scripts/ingest_ndis_policies.py")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)

    # Step 1: DB schema migrations (always runs, idempotent)
    logger.info("applying database migrations (alembic upgrade head)...")
    await asyncio.to_thread(_run_migrations)
    logger.info("database migrations applied; tables verified")

    # Step 2: Seed NDIS policy chunks if the table is empty (first boot only)
    await _maybe_ingest_policies()

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
    # ACTIVE ROUTES (in Swagger):
    app.include_router(rp_router)       # /v1/restrictive-practices/draft*, /draft/audio, /voice/session, /incidents/analyze
    app.include_router(voice_router)    # /v1/case-review/voice/session, /draft, /health/live

    # ARCHIVED ROUTES (preserved for future use, NOT in Swagger):
    # - app.include_router(router)  # /health/ready, /v1/case-review/* (context, classify, review, incident/*)
    # These are kept in code for future reference but not registered in the active API.
    # See api/archived_routes.py for documentation.

    # UNIFIED INCIDENT (main new endpoint):
    app.include_router(unified_router)  # /v1/restrictive-practices/incidents/analyze

    # SHIFT ANALYSIS (JWT, visible in Swagger):
    app.include_router(shift_analysis_router)  # /v1/case-review/shift-analysis

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

    # NDIS Compliance Suite UI (demo_ui.html) — standalone, no Streamlit needed.
    # demo_ui.html calls the API via an absolute base, so it works served from
    # any origin; behind nginx it's reachable at <host>/case-review/ui.
    @app.get("/ui", include_in_schema=False)
    async def demo_ui() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parent / "demo_ui.html",
            media_type="text/html",
        )

    return app
