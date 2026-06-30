# lambda_function.py
# Main query handler Lambda — routes by HTTP method + path (API Gateway proxy integration).
#
# Routes:
#   POST /auth/logout           → validate token, return success
#   GET  /health                → health check
#   POST /query/stream          → run full RAG pipeline (non-streaming response)
#   POST /new_session           → generate new session ID
#   POST /list_sessions         → list sessions for authenticated user
#   POST /get_turns             → get turn history for a session (ownership checked)
#   POST /rename_session        → rename session (ownership checked)
#   POST /admin/trigger_ingestion → ingest document (coordinator/superadmin)
#   POST /admin/trigger_cleanup   → clean vectors after S3 deletion (coordinator/superadmin)
#   GET  /admin/list_docs         → list org documents (coordinator/superadmin)

import json
import logging
import os
import time
import uuid

import boto3
import botocore.exceptions
import jwt

from config import (
    ADMIN_ROLES,
    BUCKET_NAME,
    DS_ID,
    KB_ID,
    ORG_PREFIX,
    REGION,
)
from memory import create_session, get_sessions, get_turns, rename_session
from pipeline import run_pipeline
from registry import now_iso, registry_create, registry_get, registry_list_by_org, registry_update

logger = logging.getLogger()
logger.setLevel(logging.INFO)

JWT_SECRET    = os.environ.get("JWT_SECRET")
JWT_ALGORITHM = "HS256"

s3            = boto3.client("s3",            region_name=REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _decode_token(authorization: str) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise ValueError("Missing or malformed Authorization header")
    if not JWT_SECRET:
        raise ValueError("JWT_SECRET not configured")
    raw    = authorization.split(" ", 1)[1]
    claims = jwt.decode(raw, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    if not claims.get("org_id") or not claims.get("role"):
        raise ValueError("Token missing required claims")
    return claims


def _extract_org_id_from_key(s3_key: str) -> str | None:
    if not s3_key.startswith(ORG_PREFIX):
        return None
    remainder = s3_key[len(ORG_PREFIX):]
    parts     = remainder.split("/")
    if len(parts) < 2:
        return None
    return parts[0]


def _verify_api_key(headers: dict):
    return


def _run_ingestion_job(doc_id: str) -> tuple[str, str]:
    job    = bedrock_agent.start_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID)
    job_id = job["ingestionJob"]["ingestionJobId"]
    registry_update(doc_id, {"ingestion_job_id": job_id})
    while True:
        status_resp = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=KB_ID, dataSourceId=DS_ID, ingestionJobId=job_id
        )["ingestionJob"]
        status = status_resp["status"]
        if status == "COMPLETE":
            return "COMPLETE", job_id
        if status == "FAILED":
            registry_update(doc_id, {"failure_reasons": str(status_resp.get("failureReasons", []))})
            return "FAILED", job_id
        time.sleep(10)


def _run_cleanup_job(doc_id: str) -> tuple[str, str]:
    job    = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=KB_ID, dataSourceId=DS_ID, dataDeletionPolicy="DELETE_NOT_FOUND"
    )
    job_id = job["ingestionJob"]["ingestionJobId"]
    registry_update(doc_id, {"cleanup_job_id": job_id})
    while True:
        status_resp = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=KB_ID, dataSourceId=DS_ID, ingestionJobId=job_id
        )["ingestionJob"]
        status = status_resp["status"]
        if status == "COMPLETE":
            return "COMPLETE", job_id
        if status == "FAILED":
            registry_update(doc_id, {"failure_reasons": str(status_resp.get("failureReasons", []))})
            return "FAILED", job_id
        time.sleep(10)


# ── Handler ────────────────────────────────────────────────────────────────────

def handler(event, context):
    method       = event.get("httpMethod", "POST")
    path         = event.get("path", "/query/stream")
    headers      = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    authorization = headers.get("authorization", "")
    query_params  = event.get("queryStringParameters") or {}

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, AttributeError) as e:
        return _resp(400, {"error": f"Invalid request body: {e}"})

    logger.info(f"{method} {path}")

    try:
        # ── GET /health ────────────────────────────────────────────────────────
        if method == "GET" and path == "/health":
            return _resp(200, {"status": "ok"})

        # ── POST /auth/logout ──────────────────────────────────────────────────
        if method == "POST" and path == "/auth/logout":
            try:
                _decode_token(authorization)
            except Exception as e:
                return _resp(401, {"error": str(e)})
            return _resp(200, {"success": True})

        # ── Remaining endpoints: require JWT ───────────────────────────────────
        try:
            claims = _decode_token(authorization)
        except Exception as e:
            return _resp(401, {"error": str(e)})

        user_id  = claims["user_id"]
        org_id   = claims["org_id"]
        role     = claims["role"]
        actor_id = f"{org_id}/{user_id}"

        # ── POST /query/stream ─────────────────────────────────────────────────
        if method == "POST" and path in ("/query/stream", "/query"):
            question = body.get("question", "").strip()
            if not question:
                return _resp(400, {"error": "question is required"})
            if role == "blocked":
                return _resp(403, {"error": "Account does not have access to this service"})

            session_id  = body.get("session_id") or str(uuid.uuid4())
            is_new_chat = body.get("is_new_chat", False)
            doc_type    = body.get("doc_type")

            result = run_pipeline(
                question    = question,
                session_id  = session_id,
                user_id     = actor_id,
                org_id      = org_id,
                role        = role,
                is_new_chat = is_new_chat,
                doc_type    = doc_type,
            )
            return _resp(200, {
                "answer":       result.get("answer", ""),
                "sources":      result.get("sources", []),
                "blocked":      result.get("blocked", False),
                "block_reason": result.get("block_reason"),
                "session_id":   result.get("session_id", session_id),
                "label":        result.get("classification", {}).get("label"),
            })

        # ── POST /new_session ──────────────────────────────────────────────────
        if method == "POST" and path == "/new_session":
            return _resp(200, {"session_id": str(uuid.uuid4())})

        # ── POST /list_sessions ────────────────────────────────────────────────
        if method == "POST" and path == "/list_sessions":
            return _resp(200, {"sessions": get_sessions(actor_id)})

        # ── POST /get_turns ────────────────────────────────────────────────────
        if method == "POST" and path == "/get_turns":
            session_id = body.get("session_id")
            if not session_id:
                return _resp(400, {"error": "session_id is required"})
            sessions = get_sessions(actor_id)
            if session_id not in [s["session_id"] for s in sessions]:
                return _resp(403, {"error": "Access denied — session not found for this user"})
            return _resp(200, {"turns": get_turns(session_id)})

        # ── POST /rename_session ───────────────────────────────────────────────
        if method == "POST" and path == "/rename_session":
            session_id = body.get("session_id")
            new_title  = body.get("title")
            if not session_id or not new_title:
                return _resp(400, {"error": "session_id and title are required"})
            sessions = get_sessions(actor_id)
            if session_id not in [s["session_id"] for s in sessions]:
                return _resp(403, {"error": "Access denied — session not found for this user"})
            rename_session(actor_id, session_id, new_title)
            return _resp(200, {"success": True})

        # ── Admin endpoints: also require API key ──────────────────────────────
        try:
            _verify_api_key(headers)
        except PermissionError as e:
            return _resp(401, {"error": str(e)})

        # ── POST /admin/trigger_ingestion ──────────────────────────────────────
        if method == "POST" and path == "/admin/trigger_ingestion":
            if role not in ADMIN_ROLES:
                return _resp(403, {"error": "Not authorised"})

            s3_key   = body.get("s3_key", "").strip()
            doc_type = body.get("doc_type", "policy")
            doc_org  = _extract_org_id_from_key(s3_key)
            filename = s3_key.split("/")[-1]

            if not doc_org:
                return _resp(400, {"error": f"Invalid S3 key format. Expected: {ORG_PREFIX}<org_id>/filename.pdf"})
            if role == "coordinator" and doc_org != org_id:
                return _resp(403, {"error": f"You can only manage documents for your own organisation ({org_id})"})
            if not s3_key.lower().endswith((".pdf", ".docx")):
                return _resp(400, {"error": "Only PDF and DOCX files are supported"})

            try:
                s3.head_object(Bucket=BUCKET_NAME, Key=s3_key)
            except botocore.exceptions.ClientError as e:
                code = e.response["Error"]["Code"]
                if code in ("404", "NoSuchKey"):
                    return _resp(404, {"error": f"File not found in S3: s3://{BUCKET_NAME}/{s3_key}"})
                return _resp(502, {"error": f"S3 error: {e}"})

            doc_id   = s3_key
            existing = registry_get(doc_id)
            if existing:
                registry_update(doc_id, {"status": "INGESTING"})
            else:
                registry_create(doc_id, doc_org, filename, BUCKET_NAME)

            try:
                s3.put_object(
                    Bucket=BUCKET_NAME,
                    Key=f"{s3_key}.metadata.json",
                    Body=json.dumps({"metadataAttributes": {"org_id": doc_org, "doc_type": doc_type}}),
                    ContentType="application/json",
                )
            except Exception as e:
                registry_update(doc_id, {"status": "FAILED", "failure_reasons": str(e)})
                return _resp(500, {"error": f"Metadata sidecar creation failed: {e}"})

            try:
                final_status, job_id = _run_ingestion_job(doc_id)
            except Exception as e:
                registry_update(doc_id, {"status": "FAILED", "failure_reasons": str(e)})
                return _resp(500, {"error": f"Ingestion job failed: {e}"})

            registry_update(doc_id, {"status": final_status})
            return _resp(200, {
                "status":   final_status,
                "doc_id":   doc_id,
                "org_id":   doc_org,
                "filename": filename,
                "job_id":   job_id,
            })

        # ── POST /admin/trigger_cleanup ────────────────────────────────────────
        if method == "POST" and path == "/admin/trigger_cleanup":
            if role not in ADMIN_ROLES:
                return _resp(403, {"error": "Not authorised"})

            s3_key  = body.get("s3_key", "").strip()
            doc_org = _extract_org_id_from_key(s3_key)

            if not doc_org:
                return _resp(400, {"error": f"Invalid S3 key format. Expected: {ORG_PREFIX}<org_id>/filename.pdf"})
            if role == "coordinator" and doc_org != org_id:
                return _resp(403, {"error": f"You can only manage documents for your own organisation ({org_id})"})

            try:
                s3.head_object(Bucket=BUCKET_NAME, Key=s3_key)
                return _resp(400, {"error": "File still exists in S3. Delete it first, then call this endpoint."})
            except botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                    return _resp(502, {"error": f"S3 error: {e}"})
                # File not found — good, proceed with cleanup

            doc_id = s3_key
            registry_update(doc_id, {"status": "DELETING"})

            try:
                s3.delete_object(Bucket=BUCKET_NAME, Key=f"{s3_key}.metadata.json")
            except Exception as e:
                logger.warning(f"Metadata sidecar delete failed (may not exist): {e}")

            try:
                final_status, job_id = _run_cleanup_job(doc_id)
            except Exception as e:
                registry_update(doc_id, {"status": "FAILED", "failure_reasons": str(e)})
                return _resp(500, {"error": f"Cleanup job failed: {e}"})

            registry_update(doc_id, {"status": "DELETED", "deleted_at": now_iso()})
            return _resp(200, {
                "status": final_status,
                "doc_id": doc_id,
                "org_id": doc_org,
                "job_id": job_id,
            })

        # ── GET /admin/list_docs ───────────────────────────────────────────────
        if method == "GET" and path == "/admin/list_docs":
            if role not in ADMIN_ROLES:
                return _resp(403, {"error": "Not authorised"})
            list_org_id = query_params.get("org_id", org_id)
            if role != "superadmin" and list_org_id != org_id:
                return _resp(403, {"error": "You can only view your own organisation's documents"})
            docs = registry_list_by_org(list_org_id)
            return _resp(200, {"org_id": list_org_id, "docs": docs, "count": len(docs)})

        return _resp(404, {"error": f"Unknown route: {method} {path}"})

    except Exception as e:
        logger.error(f"Lambda error: {e}", exc_info=True)
        return _resp(500, {"error": "Internal server error"})


def _resp(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type":                 "application/json",
            "Access-Control-Allow-Origin":  "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Api-Key",
            "Access-Control-Allow-Methods": "POST,GET,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }
