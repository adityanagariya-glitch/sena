import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from db.session import create_tables

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
