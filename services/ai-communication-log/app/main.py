import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api.sentiment_batch import router as sentiment_batch_router
from app.models.schemas import HealthResponse

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "AI batch sentiment analysis service for Sena platform. "
        "Analyses support_worker ↔ client conversations for NDIS compliance — "
        "returns full per-message sentiment, risk, breakdown, outcome, and recommended action. "
        "Powered by AWS Bedrock (Claude Sonnet, Sydney region)."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS — restrict in production ────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # TODO: lock down to Sena backend IPs in production
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ── API Key Middleware ────────────────────────────────────────────────────────
_PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)
    if not settings.API_KEY:
        return await call_next(request)
    if request.headers.get("X-API-Key") != settings.API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(sentiment_batch_router, prefix="/api/v1", tags=["Sentiment Batch"])


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
)
def health():
    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        model=settings.BEDROCK_MODEL_ID,
    )
