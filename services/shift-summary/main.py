import logging
import logging.config

from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware

from auth import require_api_key
from bedrock import consolidate_summaries
from config import get_settings
from schemas import SummarizeRequest, SummarizeResponse, ErrorResponse, TokenUsage

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── App factory ──────────────────────────────────────────────────────────────
settings = get_settings()

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten in production
    allow_methods=["POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"], include_in_schema=False)
async def health_check():
    """Lightweight liveness probe — no auth required."""
    return {"status": "ok", "version": settings.app_version}


@app.post(
    "/summarize",
    response_model=SummarizeResponse,
    status_code=status.HTTP_200_OK,
    tags=["Summarization"],
    summary="Consolidate N summaries into one",
    description=(
        "Accepts a list of text summaries, sends them to AWS Bedrock (Claude), "
        "and returns a single consolidated summary."
    ),
    dependencies=[Depends(require_api_key)],
)
async def summarize(payload: SummarizeRequest) -> SummarizeResponse:
    logger.info("Received /summarize request with %d summaries.", len(payload.summaries))
    consolidated, usage = await consolidate_summaries(payload.summaries)
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    return SummarizeResponse(
        consolidated_summary=consolidated,
        token_usage=TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )
