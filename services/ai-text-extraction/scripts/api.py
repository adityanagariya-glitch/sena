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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
#       deploying to production.
#       Example: allow_origins=["https://your-frontend.com"]
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# The backend team should add API key / JWT verification before this API is
# exposed beyond the internal network.
#
# Example with a simple API key header check:
#
#   from fastapi import Security
#   from fastapi.security.api_key import APIKeyHeader
#
#   API_KEY_HEADER = APIKeyHeader(name="X-API-Key")
#
#   async def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
#       if api_key != os.environ["EXTRACTION_API_KEY"]:
#           raise HTTPException(status_code=403, detail="Invalid API key")
#
# Then add `dependencies=[Depends(verify_api_key)]` to each protected route.
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
def extract_from_s3(req: ExtractionRequest):
    """
    Download a document from S3 by object key and extract identity fields.

    The caller (backend) must have already uploaded the document to S3 and
    obtained the object key before calling this endpoint.

    Returns a JSON object with 7 fields — see ExtractionResult.to_api_response().
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
