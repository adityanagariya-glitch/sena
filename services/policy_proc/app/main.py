# app/main.py
"""
SENA RAG API
------------
- JWT auth on every protected endpoint
- POST /auth/login  — validates fake_users.json, returns signed JWT
- POST /query/stream — SSE streaming response
- POST /query       — standard JSON response

Run:
    uvicorn app.main:app --reload --port 8000
"""
import sys
import os
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import jwt
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

import boto3
import time
from scripts.registry import registry_create, registry_update, registry_get, registry_list_by_org
from scripts.config import BUCKET_NAME, KB_ID, DS_ID, ADMIN_ROLES, ORG_PREFIX, ORG_ADMIN

from scripts.pipeline import run_pipeline
from scripts.generator import generate_stream
from scripts.classifier import classify, should_block
from scripts.retriever import retrieve, is_context_empty
from scripts.memory import (
    get_sessions, get_turns, rename_session,
    get_memory_context, save_memory, create_session,
)
from scripts.config import MESSAGES
from scripts.registry import now_iso

# ── Config ─────────────────────────────────────────────────────────────────────
s3            = boto3.client("s3",            region_name="ap-southeast-2")
bedrock_agent = boto3.client("bedrock-agent", region_name="ap-southeast-2")

JWT_SECRET    = os.environ.get("JWT_SECRET", "sena-local-qa-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
TOKEN_TTL     = 3600  # seconds

USERS_FILE    = os.environ.get("SENA_USERS_FILE",
                    os.path.join(os.path.dirname(__file__), "..", "fake_users.json"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SENA RAG API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── User store ─────────────────────────────────────────────────────────────────

def _load_users() -> dict:
    """Load fake_users.json and index by login_id (lowercase)."""
    try:
        with open(USERS_FILE) as f:
            data = json.load(f)
        return {
            u["login_id"].lower(): u
            for u in data.get("users", [])
        }
    except FileNotFoundError:
        logger.warning(f"Users file not found: {USERS_FILE}")
        return {}
    except Exception as exc:
        logger.error(f"Failed to load users file: {exc}")
        return {}


# ── JWT ─────────────────────────────────────────────────────────────────────────

def _mint_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub":       user["user_id"],
            "user_id":   user["user_id"],
            "org_id":    user["org_id"],
            "role":      user["role"],
            "full_name": user.get("full_name", ""),
            "login_id":  user["login_id"],
            "iat":       now,
            "exp":       now + timedelta(seconds=TOKEN_TTL),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(authorization: str) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
    if not claims.get("org_id"):
        raise HTTPException(status_code=401, detail="Token missing org_id claim")
    if not claims.get("role"):
        raise HTTPException(status_code=401, detail="Token missing role claim")
    return claims

# ── Pydantic models ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    login_id: str   # e.g. "org1\alice.walker"
    password: str


class QueryRequest(BaseModel):
    question:      str
    session_id:    Optional[str] = None
    session_title: Optional[str] = None
    is_new_chat:   bool = False


class TurnsRequest(BaseModel):
    session_id: str


class RenameRequest(BaseModel):
    session_id: str
    title:      str

class TriggerIngestionRequest(BaseModel):
    s3_key: str

class TriggerCleanupRequest(BaseModel):
    s3_key: str


# ── Auth endpoint ──────────────────────────────────────────────────────────────

@app.post("/auth/login")
def login(req: LoginRequest):
    """
    Validates login_id + password against fake_users.json.
    Returns a signed JWT on success.
    """
    users = _load_users()
    user  = users.get(req.login_id.lower().strip())

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("active", False):
        raise HTTPException(status_code=403, detail="Account is inactive")
    if user["password"] != req.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _mint_token(user)
    logger.info(f"Login OK | user={user['user_id']} org={user['org_id']} role={user['role']}")

    return {
        "token":     token,
        "user_id":   user["user_id"],
        "org_id":    user["org_id"],
        "role":      user["role"],
        "full_name": user.get("full_name", ""),
        "login_id":  user["login_id"],
    }


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Query (streaming) ──────────────────────────────────────────────────────────

@app.post("/query/stream")
def query_stream(req: QueryRequest, authorization: str = Header(default=None)):
    """
    SSE streaming. Events:
        data: {"type": "meta",    "session_id": "...", "label": "...", "sources": [...]}
        data: {"type": "token",   "text": "..."}
        data: {"type": "done",    "stop_reason": "end_turn"}
        data: {"type": "blocked", "text": "...", "label": "..."}
        data: {"type": "error",   "text": "..."}
    """
    claims  = decode_token(authorization)
    user_id = claims["user_id"]
    org_id  = claims["org_id"]
    role    = claims["role"]
    actor_id = f"{org_id}/{user_id}"
    session_id    = req.session_id or str(uuid.uuid4())
    session_title = req.session_title or req.question[:60]
    question      = req.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="question cannot be empty")

    logger.info(f"Stream | user={user_id} | org={org_id} | role={role} | q={question[:60]}")

    def event_stream():
        try:
            result = run_pipeline(
                question    = question,
                session_id  = session_id,
                user_id     = actor_id,
                org_id      = org_id,
                role        = role,
                is_new_chat = req.is_new_chat,
            )
        except Exception as exc:
            logger.error(f"Pipeline error: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'text': MESSAGES['ERROR']})}\n\n"
            return

        answer       = result.get("answer", "")
        sources      = result.get("sources", [])
        blocked      = result.get("blocked", False)
        block_reason = result.get("block_reason")
        label        = result.get("classification", {}).get("label")

        yield f"data: {json.dumps({'type': 'meta', 'session_id': result.get('session_id', session_id), 'label': label, 'sources': sources, '_identity': {'user_id': user_id, 'org_id': org_id, 'role': role}})}\n\n"

        if blocked:
            yield f"data: {json.dumps({'type': 'blocked', 'text': answer, 'label': block_reason or label})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'token', 'text': answer})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'stop_reason': 'end_turn'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ── Session endpoints ──────────────────────────────────────────────────────────

@app.post("/new_session")
def new_session(authorization: str = Header(default=None)):
    decode_token(authorization)
    return {"session_id": str(uuid.uuid4())}


@app.post("/list_sessions")
def list_sessions(authorization: str = Header(default=None)):
    claims  = decode_token(authorization)
    user_id = claims["user_id"]
    org_id  = claims["org_id"]
    actor_id = f"{org_id}/{user_id}"
    return {"sessions": get_sessions(actor_id)}


@app.post("/get_turns")
def get_turns_endpoint(req: TurnsRequest, authorization: str = Header(default=None)):
    claims   = decode_token(authorization)
    user_id  = claims["user_id"]
    org_id   = claims["org_id"]
    actor_id = f"{org_id}/{user_id}"
    # Validate session belongs to this user before returning turns
    sessions = get_sessions(actor_id)
    session_ids = [s["session_id"] for s in sessions]
    if req.session_id not in session_ids:
        raise HTTPException(status_code=403, detail="Access denied — session not found for this user")
    return {"turns": get_turns(req.session_id)}


@app.post("/rename_session")
def rename(req: RenameRequest, authorization: str = Header(default=None)):
    claims  = decode_token(authorization)
    user_id = claims["user_id"]
    org_id  = claims["org_id"]
    actor_id = f"{org_id}/{user_id}"
    return {"success": rename_session(actor_id, req.session_id, req.title)}

# ── Registry functions (auto update and delete) ──────────────────────────────────────────────────────────
def extract_org_id_from_key(s3_key: str) -> str | None:
    """Extracts org_id from S3 key path. e.g. sena/misty/orgs/org_sunrise/file.pdf → org_sunrise"""
    if not s3_key.startswith(ORG_PREFIX):
        return None
    remainder = s3_key[len(ORG_PREFIX):]
    parts = remainder.split("/")
    if len(parts) < 2:
        return None
    return parts[0]
 
 
def run_ingestion_job(doc_id: str) -> tuple[str, str]:
    """
    Starts Bedrock KB ingestion job and polls until complete.
    Returns (final_status, job_id).
    """
    job    = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=KB_ID,
        dataSourceId=DS_ID
    )
    job_id = job["ingestionJob"]["ingestionJobId"]
    logger.info(f"Ingestion job started: {job_id}")
 
    registry_update(doc_id, {"ingestion_job_id": job_id})
 
    while True:
        response = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=KB_ID,
            dataSourceId=DS_ID,
            ingestionJobId=job_id
        )["ingestionJob"]
 
        status = response["status"]
        logger.info(f"Ingestion job {job_id} — status: {status}")
 
        if status == "COMPLETE":
            docs_indexed = response.get("statistics", {}).get("numberOfNewDocumentsIndexed", 0)
            logger.info(f"Ingestion complete — {docs_indexed} docs indexed")
            return "COMPLETE", job_id
 
        elif status == "FAILED":
            failure_reasons = response.get("failureReasons", [])
            logger.error(f"Ingestion failed: {failure_reasons}")
            registry_update(doc_id, {"failure_reasons": str(failure_reasons)})
            return "FAILED", job_id
 
        time.sleep(10)
 
 
def run_cleanup_job(doc_id: str) -> tuple[str, str]:
    """
    Starts Bedrock KB ingestion job with DELETE_NOT_FOUND policy.
    Polls until complete. Returns (final_status, job_id).
    """
    job    = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=KB_ID,
        dataSourceId=DS_ID,
        dataDeletionPolicy="DELETE_NOT_FOUND"
    )
    job_id = job["ingestionJob"]["ingestionJobId"]
    logger.info(f"Cleanup job started: {job_id}")
 
    registry_update(doc_id, {"cleanup_job_id": job_id})
 
    while True:
        response = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=KB_ID,
            dataSourceId=DS_ID,
            ingestionJobId=job_id
        )["ingestionJob"]
 
        status = response["status"]
        logger.info(f"Cleanup job {job_id} — status: {status}")
 
        if status == "COMPLETE":
            docs_deleted = response.get("statistics", {}).get("numberOfDeletedDocuments", 0)
            logger.info(f"Cleanup complete — {docs_deleted} docs removed from index")
            return "COMPLETE", job_id
 
        elif status == "FAILED":
            failure_reasons = response.get("failureReasons", [])
            logger.error(f"Cleanup failed: {failure_reasons}")
            registry_update(doc_id, {"failure_reasons": str(failure_reasons)})
            return "FAILED", job_id
 
        time.sleep(10)
 
 
# ══════════════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS — add these to main.py
# ══════════════════════════════════════════════════════════════════════════════
 
@app.post("/admin/trigger_ingestion")
def trigger_ingestion(req: TriggerIngestionRequest, authorization: str = Header(default=None)):
    """
    Triggers ingestion for a document already uploaded to S3.
    
    Flow:
        1. Validate role — coordinator or superadmin only
        2. Validate S3 key format and extract org_id
        3. Verify file exists in S3
        4. Create .metadata.json sidecar
        5. Create registry entry (status: INGESTING)
        6. Start ingestion job — wait for completion
        7. Update registry (status: COMPLETE or FAILED)
    
    Call after manually uploading a file to S3.
    Synchronous — waits for ingestion to complete (2-3 mins).
    """
    claims  = decode_token(authorization)
    role    = claims["role"]
    user_id = claims["user_id"]
    org_id  = claims["org_id"]
 
    # Role check
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorised")
 
    s3_key   = req.s3_key.strip()
    doc_org  = extract_org_id_from_key(s3_key)
    filename = s3_key.split("/")[-1]
 
    # Validate key format
    if not doc_org:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid S3 key format. Expected: {ORG_PREFIX}<org_id>/filename.pdf"
        )
 
    # Coordinators can only trigger ingestion for their own org
    if role == "coordinator" and doc_org != org_id:
        raise HTTPException(
            status_code=403,
            detail=f"You can only manage documents for your own organisation ({org_id})"
        )
 
    # Verify file exists in S3
    try:
        s3.head_object(Bucket=BUCKET_NAME, Key=s3_key)
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"File not found in S3: s3://{BUCKET_NAME}/{s3_key}"
        )
 
    # Check file type
    if not s3_key.lower().endswith((".pdf", ".docx")):
        raise HTTPException(
            status_code=400,
            detail="Only PDF and DOCX files are supported"
        )
 
    logger.info(f"Trigger ingestion | user={user_id} | org={doc_org} | key={s3_key}")
 
    doc_id = s3_key
 
    # Create or update registry entry
    try:
        existing = registry_get(doc_id)
        if existing:
            logger.info(f"Doc already in registry — updating status to INGESTING: {doc_id}")
            registry_update(doc_id, {"status": "INGESTING"})
        else:
            registry_create(doc_id, doc_org, filename, BUCKET_NAME)
    except Exception as e:
        logger.error(f"Registry create/update failed: {e}")
        raise HTTPException(status_code=500, detail=f"Registry error: {e}")
 
    # Create metadata sidecar
    try:
        metadata_key = f"{s3_key}.metadata.json"
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=metadata_key,
            Body=json.dumps({"metadataAttributes": {"org_id": doc_org}}),
            ContentType="application/json"
        )
        logger.info(f"Metadata sidecar created: {metadata_key}")
    except Exception as e:
        registry_update(doc_id, {"status": "FAILED", "failure_reasons": str(e)})
        raise HTTPException(status_code=500, detail=f"Metadata sidecar creation failed: {e}")
 
    # Run ingestion job — synchronous, waits for completion
    try:
        final_status, job_id = run_ingestion_job(doc_id)
    except Exception as e:
        registry_update(doc_id, {"status": "FAILED", "failure_reasons": str(e)})
        raise HTTPException(status_code=500, detail=f"Ingestion job failed: {e}")
 
    # Update registry
    registry_update(doc_id, {"status": final_status})
 
    # Clear org doc cache so retriever picks up new doc immediately
    from scripts.retriever import clear_org_cache
    clear_org_cache(doc_org)
 
    return {
        "status":   final_status,
        "doc_id":   doc_id,
        "org_id":   doc_org,
        "filename": filename,
        "job_id":   job_id
    }
 
 
@app.post("/admin/trigger_cleanup")
def trigger_cleanup(req: TriggerCleanupRequest, authorization: str = Header(default=None)):
    """
    Triggers vector cleanup after a document has been deleted from S3.
 
    Flow:
        1. Validate role — coordinator or superadmin only
        2. Validate S3 key format and extract org_id
        3. Confirm file is gone from S3 (cleanup only makes sense after deletion)
        4. Delete .metadata.json sidecar if it exists
        5. Update registry (status: DELETING)
        6. Start cleanup job with DELETE_NOT_FOUND — wait for completion
        7. Update registry (status: DELETED)
 
    Call after manually deleting a file from S3.
    Synchronous — waits for cleanup to complete (2-3 mins).
    """
    claims  = decode_token(authorization)
    role    = claims["role"]
    user_id = claims["user_id"]
    org_id  = claims["org_id"]
 
    # Role check
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorised")
 
    s3_key  = req.s3_key.strip()
    doc_org = extract_org_id_from_key(s3_key)
 
    # Validate key format
    if not doc_org:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid S3 key format. Expected: {ORG_PREFIX}<org_id>/filename.pdf"
        )
 
    # Coordinators can only manage their own org
    if role == "coordinator" and doc_org != org_id:
        raise HTTPException(
            status_code=403,
            detail=f"You can only manage documents for your own organisation ({org_id})"
        )
 
    # Confirm file is actually gone from S3
    try:
        s3.head_object(Bucket=BUCKET_NAME, Key=s3_key)
        # If we reach here the file still exists
        raise HTTPException(
            status_code=400,
            detail=f"File still exists in S3. Delete it first, then call this endpoint."
        )
    except HTTPException:
        raise
    except Exception:
        # File not found — good, proceed with cleanup
        pass
 
    logger.info(f"Trigger cleanup | user={user_id} | org={doc_org} | key={s3_key}")
 
    doc_id = s3_key
 
    # Update registry to DELETING
    registry_update(doc_id, {"status": "DELETING"})
 
    # Delete metadata sidecar if it exists
    try:
        metadata_key = f"{s3_key}.metadata.json"
        s3.delete_object(Bucket=BUCKET_NAME, Key=metadata_key)
        logger.info(f"Metadata sidecar deleted: {metadata_key}")
    except Exception as e:
        logger.warning(f"Metadata sidecar delete failed (may not exist): {e}")
 
    # Run cleanup job — synchronous, waits for completion
    try:
        final_status, job_id = run_cleanup_job(doc_id)
    except Exception as e:
        registry_update(doc_id, {"status": "FAILED", "failure_reasons": str(e)})
        raise HTTPException(status_code=500, detail=f"Cleanup job failed: {e}")
 
    # Update registry — permanent record
    registry_update(doc_id, {
        "status":     "DELETED",
        "deleted_at": now_iso()
    })
 
    # Clear org doc cache
    from scripts.retriever import clear_org_cache
    clear_org_cache(doc_org)
 
    return {
        "status":  final_status,
        "doc_id":  doc_id,
        "org_id":  doc_org,
        "job_id":  job_id
    }
 
 
@app.get("/admin/list_docs")
def list_docs(org_id: str, authorization: str = Header(default=None)):
    """
    Lists all documents in the registry for a given org.
    Coordinators can only list their own org. Superadmin can list any.
    """
    claims = decode_token(authorization)
    role   = claims["role"]
    caller_org = claims["org_id"]
 
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorised")
 
    if role not in ORG_ADMIN and org_id != caller_org:
        raise HTTPException(status_code=403, detail="You can only view your own organisation's documents")
 
    docs = registry_list_by_org(org_id)
    return {"org_id": org_id, "docs": docs, "count": len(docs)}