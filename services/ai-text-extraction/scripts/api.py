"""
api.py
------
FastAPI application exposing the document extraction pipeline as an HTTP API.

Endpoints:
  POST /extract        — Production: accepts an S3 object key, returns extraction JSON.
  POST /extract/local  — Local testing only: accepts a local file path.
  GET  /health         — Health check.

Start the server:
  uvicorn scripts.api:app --host 0.0.0.0 --port 8000 --reload

Environment variables required for production:
  S3_BUCKET_NAME   — The S3 bucket where documents are stored.
  AWS_REGION       — Optional, defaults to ap-southeast-2.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv
# Loads .env for local development. In Docker, env vars are injected by Docker itself.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=False)

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scripts.auth import verify_jwt
from scripts.pipeline import run, run_from_s3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Document Extraction API",
    description="Extracts structured fields from identity documents using AWS Bedrock Nova Lite.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS
# TODO: Replace the wildcard origin with your actual frontend domain(s) before
#       deploying to production.
#       Example: allow_origins=["https://your-frontend.com"]
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # TODO: restrict to frontend origin in production
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Authentication
# POST /extract is protected by JWT Bearer token validation (see scripts/auth.py).
# The token is issued by the auth server and passed here by the mobile client.
# GET /health and POST /extract/local are intentionally unprotected.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ExtractionRequest(BaseModel):
    """Request body for the production S3 endpoint."""
    s3_key: str

    model_config = {"json_schema_extra": {"example": {"s3_key": "uploads/2024/passport.pdf"}}}


class LocalExtractionRequest(BaseModel):
    """Request body for the local-testing endpoint."""
    file_path: str

    model_config = {"json_schema_extra": {"example": {"file_path": "C:/Users/BAPS/Documents/SENA_text-extraction/test_data/WA_Photo_card.jpg"}}}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Utility"])
def health():
    """Returns 200 OK when the service is running."""
    return {"status": "ok"}


@app.post("/extract", tags=["Extraction"])
def extract_from_s3(
    req: ExtractionRequest,
    _token_payload: dict = Depends(verify_jwt),
):
    """
    Download a document from S3 by object key and extract identity fields.

    Requires a valid JWT in the Authorization header:
      Authorization: Bearer <token>

    The token is issued by the auth server (mobile team) and validated here.
    Returns a JSON object with the extracted identity fields.
    """
    logger.info("POST /extract — s3_key=%s", req.s3_key)

    try:
        result = run_from_s3(req.s3_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        # Unsupported file type or missing S3_BUCKET_NAME
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during S3 extraction")
        raise HTTPException(status_code=500, detail="Extraction failed — see server logs.")

    return result.to_api_response()


@app.post("/extract/local", tags=["Local Testing"])
def extract_local(req: LocalExtractionRequest):
    """
    Extract identity fields from a local file path.

    FOR LOCAL TESTING ONLY — this endpoint reads directly from the filesystem
    and should not be exposed in production.

    Accepts absolute file paths to .jpg, .jpeg, .png, .webp, .pdf, or .docx files.
    """
    logger.info("POST /extract/local — file_path=%s", req.file_path)

    file_path = Path(req.file_path)

    try:
        result = run(file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during local extraction")
        raise HTTPException(status_code=500, detail="Extraction failed — see server logs.")

    return result.to_api_response()
