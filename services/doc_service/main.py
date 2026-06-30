"""
SENA Document Service
---------------------
Standalone FastAPI service for document management (upload + delete).
Runs independently from the query API — separate Docker container, port 8001.

Endpoints:
  POST   /documents/upload          — upload file, trigger async KB ingestion
  DELETE /documents/{doc_id}        — delete from S3 + KB index, async
  GET    /documents/status/{doc_id} — poll ingestion or deletion status
  GET    /documents/list            — list docs for an org
  GET    /health                    — liveness check
"""
import logging
import os

from fastapi import FastAPI, Depends, Header, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from auth import decode_token, require_admin, require_org_access
from rsa_auth import verify_rsa
from pipeline import run_upload, run_delete, poll_and_update, SUPPORTED_EXTENSIONS
from registry import registry_get, registry_list_by_org, registry_update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SENA Document Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/documents/upload", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file:             UploadFile = File(...),
    org_id:           str        = Form(...),
    doc_type:         str        = Form("policy"),
    _:                None       = Depends(verify_rsa),
):
    """
    Accept a document from the frontend, run the full ingestion pipeline:
      1. Upload raw file → S3 orgs/{org_id}/
      2. Convert to .md → S3 md/orgs/{org_id}/
      3. Upload metadata sidecar (.md.metadata.json)
      4. Write registry entry (status: INGESTING)
      5. Trigger Bedrock KB ingestion job
      6. Return 202 — background task polls until COMPLETE/FAILED

    Auth: RSA request signature (X-AI-Signature over "{ts}." + raw body).
    """
    if doc_type not in ("policy", "procedure"):
        raise HTTPException(status_code=400, detail="doc_type must be 'policy' or 'procedure'")

    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        doc_id, job_id = run_upload(
            file_bytes=file_bytes,
            filename=filename,
            org_id=org_id,
            doc_type=doc_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload pipeline error: {e}")
        raise HTTPException(status_code=500, detail="Upload pipeline failed. Check server logs.")

    background_tasks.add_task(poll_and_update, doc_id, job_id)

    return {
        "doc_id":   doc_id,
        "job_id":   job_id,
        "org_id":   org_id,
        "filename": filename,
        "doc_type": doc_type,
        "status":   "INGESTING",
        "message":  "Document uploaded. Poll /documents/status/{doc_id} for completion.",
    }


# ── Delete ────────────────────────────────────────────────────────────────────

@app.delete("/documents/{doc_id:path}", status_code=202)
def delete_document(
    doc_id:           str,
    background_tasks: BackgroundTasks,
    _:                None = Depends(verify_rsa),
):
    """
    Delete a document:
      1. Guard against double-delete
      2. Mark registry as DELETING — return 202
      3. Background: delete S3 raw + md + sidecar, remove from KB index, mark DELETED

    Auth: RSA request signature (X-AI-Signature over "{ts}.DELETE {path}").
    """
    item = registry_get(doc_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    if item["status"] in ("DELETING", "DELETED"):
        raise HTTPException(
            status_code=409,
            detail=f"Document is already {item['status'].lower()}",
        )

    registry_update(doc_id, {"status": "DELETING"})
    background_tasks.add_task(run_delete, doc_id, item["org_id"], item["filename"])

    return {
        "doc_id":   doc_id,
        "org_id":   item["org_id"],
        "filename": item["filename"],
        "status":   "DELETING",
        "message":  "Deletion started. Poll /documents/status/{doc_id} for completion.",
    }


# ── Status (shared by upload and delete flows) ────────────────────────────────

@app.get("/documents/status/{doc_id:path}")
def document_status(
    doc_id:        str,
    authorization: str = Header(default=None),
):
    """
    Returns registry entry for doc_id.
    Works for both ingestion (INGESTING → COMPLETE) and deletion (DELETING → DELETED).
    doc_id is the .md S3 key — URL-encode slashes when calling from clients.
    """
    claims = decode_token(authorization)
    require_admin(claims)

    item = registry_get(doc_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    require_org_access(claims, item["org_id"])
    return item


# ── List ──────────────────────────────────────────────────────────────────────

@app.get("/documents/list")
def list_documents(
    org_id: str,
    _:      None = Depends(verify_rsa),
):
    """List all registry entries for an organisation.

    Auth: RSA request signature (X-AI-Signature over "{ts}.GET {path}?org_id=...").
    """
    docs = registry_list_by_org(org_id)
    return {"org_id": org_id, "count": len(docs), "documents": docs}
