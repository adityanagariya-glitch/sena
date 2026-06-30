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

# Load .env before any config imports so all env vars are available at import time
from dotenv import load_dotenv
load_dotenv()

import uuid
import json
import logging
import time
import time as _time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from enum import Enum
import requests as http_requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import jwt
import botocore.exceptions
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

import boto3
from registry import registry_create, registry_update, registry_get, registry_list_by_org
from config import BUCKET_NAME, KB_ID, DS_ID, ADMIN_ROLES, ORG_PREFIX, ORG_ADMIN, BACKEND_API_BASE, REGION

from pipeline import run_pipeline, run_pipeline_stream
from generator import generate_stream
from classifier import classify, should_block
from retriever import retrieve, is_context_empty
from memory import (
    get_sessions, get_turns, rename_session,
    get_memory_context, save_memory, create_session,
)
from config import MESSAGES
from registry import now_iso

# ── Config ─────────────────────────────────────────────────────────────────────
s3            = boto3.client("s3",            region_name=REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)

JWT_ENABLED = os.environ.get("JWT_ENABLED", "false").lower() == "true"
JWT_SECRET  = os.environ.get("JWT_SECRET", "")
if JWT_ENABLED and not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is not set")
JWT_ALGORITHM = "HS256"
TOKEN_TTL     = 3600  # seconds

USERS_FILE    = os.environ.get("SENA_USERS_FILE",
                    os.path.join(os.path.dirname(__file__), "..", "fake_users.json"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Login rate limiter ─────────────────────────────────────────────────────────
_login_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60   # seconds
_RATE_LIMIT_MAX    = int(os.environ.get("LOGIN_RATE_LIMIT_MAX", "20"))  # attempts per window per IP

# ── User role cache ────────────────────────────────────────────────────────────
_user_role_cache: dict[str, tuple[str, float]] = {}  # (role, expires_at)
_ROLE_CACHE_TTL = 300  # seconds before re-checking backend

def map_user_type_to_role(user_type_response: dict) -> str:
    data      = user_type_response.get("data", {})
    user_type = data.get("userType")

    if user_type == "superAdmin":
        return "superadmin"
    elif user_type == "organizationMember":
        staff_type = data.get("staffType")
        if staff_type == "support_worker":
            return "support_worker"
        elif staff_type == "in_office":
            return "coordinator"
        else:
            return "support_worker"
    elif user_type == "serviceProvider":
        if data.get("isISW"):
            return "support_worker"
        else:
            return "coordinator"
    return "blocked"


def get_user_role(user_id: str, token: str, jwt_role: str = "support_worker") -> str:
    cached = _user_role_cache.get(user_id)
    if cached and _time.time() < cached[1]:
        return cached[0]
    if not BACKEND_API_BASE:
        # No external user service configured — trust the role embedded in the JWT.
        logger.info(f"BACKEND_API_BASE not set — using JWT role for {user_id}: {jwt_role}")
        _user_role_cache[user_id] = (jwt_role, _time.time() + _ROLE_CACHE_TTL)
        return jwt_role
    try:
        r = http_requests.get(
            f"{BACKEND_API_BASE}/api/auth/user-type",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5
        )
        r.raise_for_status()
        role = map_user_type_to_role(r.json())
        _user_role_cache[user_id] = (role, _time.time() + _ROLE_CACHE_TTL)
        logger.info(f"User role resolved: {user_id} → {role}")
        return role
    except Exception as e:
        logger.error(f"Failed to get user type from backend: {e}")
        return jwt_role

app = FastAPI(title="SENA RAG API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Internal API key guard ─────────────────────────────────────────────────────
def verify_api_key(x_api_key: str = Header(default=None)):
    return
    
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
    if not JWT_ENABLED:
        return {"user_id": "dev", "org_id": "ndis", "role": "superadmin"}
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        raw = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    # Normalise field names — support both real backend (camelCase) and local dev (snake_case)
    user_id = raw.get("user_id") or raw.get("userId") or raw.get("sub", "")
    org_id  = raw.get("org_id")  or raw.get("organizationId", "")
    role    = raw.get("role", "")   # absent in real backend JWTs — filled later by get_user_role()

    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user identifier (user_id / userId / sub)")
    if not org_id:
        raise HTTPException(status_code=401, detail="Token missing org identifier (org_id / organizationId)")

    # Return normalised dict so all downstream code uses consistent snake_case keys
    return {**raw, "user_id": user_id, "org_id": org_id, "role": role}

# ── Pydantic models ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    login_id: str   # e.g. "org1\alice.walker"
    password: str


class DocType(str, Enum):
    POLICY    = "policy"
    PROCEDURE = "procedure"


class QueryRequest(BaseModel):
    question:      str
    session_id:    Optional[str] = None
    session_title: Optional[str] = None
    is_new_chat:   bool = False
    doc_type:      Optional[DocType] = None


class TurnsRequest(BaseModel):
    session_id: str


class RenameRequest(BaseModel):
    session_id: str
    title:      str



# ── Auth endpoint ──────────────────────────────────────────────────────────────

@app.post("/auth/login")
def login(req: LoginRequest, request: Request):
    """
    Validates login_id + password against fake_users.json.
    Returns a signed JWT on success.
    """
    client_ip = request.client.host if request.client else "unknown"
    now_ts = _time.time()
    _login_attempts[client_ip] = [t for t in _login_attempts[client_ip] if now_ts - t < _RATE_LIMIT_WINDOW]
    if not _login_attempts[client_ip]:
        del _login_attempts[client_ip]
    if len(_login_attempts.get(client_ip, [])) >= _RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a minute.")
    _login_attempts[client_ip].append(now_ts)

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


# ── Logout ─────────────────────────────────────────────────────────────────────

@app.post("/auth/logout")
def logout(authorization: str = Header(default=None)):
    """Validates token and instructs client to discard it. JWT is stateless — server cannot revoke."""
    decode_token(authorization)
    return {"success": True}


# ── Query (streaming) ──────────────────────────────────────────────────────────

@app.post("/query/stream")
def query_stream(req: QueryRequest, authorization: str = Header(default=None)):
    """
    SSE streaming. Events:
        data: {"type": "meta",    "session_id": "...", "label": "...", "sources": [...]}
        data: {"type": "token",   "text": "..."}          ← one per word, streamed live
        data: {"type": "done",    "stop_reason": "end_turn"}
        data: {"type": "usage",   "input_tokens": N, "output_tokens": N}
        data: {"type": "blocked", "text": "...", "label": "..."}
        data: {"type": "error",   "text": "..."}
    """
    claims  = decode_token(authorization)
    user_id = claims["user_id"]
    org_id  = claims["org_id"]
    role    = claims["role"]
    token = authorization.split(" ", 1)[1] if authorization else ""
    role = get_user_role(user_id, token, jwt_role=role)
    if role == "blocked":
        raise HTTPException(status_code=403, detail="Your account does not have access to this service. Contact your administrator for support.")
    actor_id = f"{org_id}/{user_id}"
    session_id    = req.session_id or str(uuid.uuid4())
    session_title = req.session_title or req.question[:60]
    question      = req.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="question cannot be empty")

    logger.info(f"Stream | user={user_id} | org={org_id} | role={role} | q={question[:60]}")

    def event_stream():
        try:
            meta_sent = False
            for event in run_pipeline_stream(
                question    = question,
                session_id  = session_id,
                user_id     = actor_id,
                org_id      = org_id,
                role        = role,
                is_new_chat = req.is_new_chat,
                doc_type    = req.doc_type.value if req.doc_type else None,
            ):
                # Inject identity into the meta event
                if event.get("type") == "meta" and not meta_sent:
                    event["_identity"] = {"user_id": user_id, "org_id": org_id, "role": role}
                    meta_sent = True
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            logger.error(f"Pipeline stream error: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'text': MESSAGES['ERROR']})}\n\n"

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
    sessions = get_sessions(actor_id)
    if req.session_id not in [s["session_id"] for s in sessions]:
        raise HTTPException(status_code=403, detail="Access denied — session not found for this user")
    return {"success": rename_session(actor_id, req.session_id, req.title)}

 
 
@app.get("/admin/list_docs")
def list_docs(org_id: str, authorization: str = Header(default=None), _: None = Depends(verify_api_key)):
    """
    Lists all documents in the registry for a given org.
    Coordinators can only list their own org. Superadmin can list any.
    """
    claims = decode_token(authorization)
    role   = claims["role"]
    caller_org = claims["org_id"]
 
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorised")
 
    if role != "superadmin" and org_id != caller_org:
        raise HTTPException(status_code=403, detail="You can only view your own organisation's documents")
 
    docs = registry_list_by_org(org_id)
    return {"org_id": org_id, "docs": docs, "count": len(docs)}