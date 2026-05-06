import logging
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from api.routes import router
from db.session import create_tables

_DEMO_HTML = Path(__file__).parent / "demo_ui.html"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="NDIS Restrictive Practice Detection",
        description="AI pipeline to detect regulated restrictive practices from NDIS case notes.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.get("/demo", include_in_schema=False)
    async def demo_ui() -> FileResponse:
        return FileResponse(_DEMO_HTML, media_type="text/html")

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        tb = traceback.format_exc()
        logger.error("Unhandled exception on %s %s:\n%s", request.method, request.url.path, tb)
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}", "traceback": tb},
        )

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("Creating DB tables...")
        try:
            await create_tables()
            logger.info("DB tables ready.")
        except Exception as exc:
            logger.warning("DB not reachable at startup — start PostgreSQL before using pipeline endpoints. (%s)", exc)
        logger.info("Startup complete.")

    return app


app = create_app()
