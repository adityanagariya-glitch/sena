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

from pipeline import run_pipeline
from generator import generate_stream
from classifier import classify, should_block
from retriever import retrieve, is_context_empty
from memory import (
    get_sessions, get_turns, rename_session,
    get_memory_context, save_memory, create_session,
)
from config import MESSAGES

# ── Config ─────────────────────────────────────────────────────────────────────

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


# # ── Query (non-streaming) ──────────────────────────────────────────────────────

# @app.post("/query")
# def query(req: QueryRequest, authorization: str = Header(default=None)):
#     claims  = decode_token(authorization)
#     user_id = claims["user_id"]
#     org_id  = claims["org_id"]
#     role    = claims["role"]
#     actor_id = f"{org_id}/{user_id}"
#     session_id    = req.session_id or str(uuid.uuid4())
#     session_title = req.session_title or req.question[:60]

#     if not req.question.strip():
#         raise HTTPException(status_code=400, detail="question cannot be empty")

#     logger.info(f"Query | user={user_id} | org={org_id} | role={role} | q={req.question[:60]}")

#     result = run_pipeline(
#         question    = req.question,
#         session_id  = session_id,
#         user_id     = user_id,
#         org_id      = org_id,
#         role        = role,
#         is_new_chat = req.is_new_chat,
#     )

#     answer       = result.get("answer")
#     sources      = result.get("sources", [])
#     blocked      = result.get("blocked", False)
#     block_reason = result.get("block_reason")
#     label        = result.get("classification", {}).get("label")
#     clean_sources = [s.split("/")[-1] for s in sources]

#     return {
#         "answer":       answer,
#         "sources":      clean_sources,
#         "blocked":      blocked,
#         "block_reason": block_reason,
#         "session_id":   result.get("session_id", session_id),
#         "label":        label,
#         "confidence":   result.get("classification", {}).get("confidence"),
#         "_identity":    {"user_id": user_id, "org_id": org_id, "role": role},
#     }


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
        # Step 1: Classify
        try:
            classification = classify(question)
        except Exception as exc:
            logger.error(f"Classifier error: {exc}")
            classification = {"label": "NDIS", "confidence": 0.5}

        blocked, block_message = should_block(classification)
        if blocked:
            save_memory(
            actor_id,
            session_id,
            question,
            block_message,
            []
        )
            yield f"data: {json.dumps({'type': 'blocked', 'text': block_message, 'label': classification.get('label')})}\n\n"
            return

        # Step 2: New session
        if req.is_new_chat:
            try:
                create_session(actor_id, session_id, question)
            except Exception as exc:
                logger.error(f"Session create error: {exc}")

        # Step 3: Memory
        try:
            memory_ctx = get_memory_context(actor_id, session_id, question)
            recent_turns  = memory_ctx["recent_turns"]
            agentcore_ctx = memory_ctx["agentcore_ctx"]
        except Exception as exc:
            logger.error(f"Memory read error: {exc}")
            recent_turns  = ""
            agentcore_ctx = ""

        # Step 4: Retrieve
        try:
            chunks, context, sources = retrieve(question, org_id=org_id, role=role)
        except Exception as exc:
            logger.error(f"Retrieval error: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'text': MESSAGES['ERROR']})}\n\n"
            return

        if is_context_empty(context):
            save_memory(
            actor_id,
            session_id,
            question,
            MESSAGES["NOT_IN_KB"],
            []
        )
            yield f"data: {json.dumps({'type': 'blocked', 'text': MESSAGES['NOT_IN_KB'], 'label': 'NOT_IN_KB'})}\n\n"
            return

        clean_sources = [s.split("/")[-1] for s in sources]

        # Step 5: Metadata event
        yield f"data: {json.dumps({'type': 'meta', 'session_id': session_id, 'label': classification.get('label'), 'sources': clean_sources, '_identity': {'user_id': user_id, 'org_id': org_id, 'role': role}})}\n\n"
        
        # # DEBUG
        # print(f"\n=== CONTEXT SENT TO GENERATOR ===\n{context[:1000]}\n=== END CONTEXT ===\n")

        # Step 6: Generate (streaming)
        full_answer   = []
        final_blocked = False
        for chunk in generate_stream(
            question,
            context,
            recent_turns,
            agentcore_ctx
        ):
            ctype = chunk.get("type")
            # token
            if ctype == "token":
                text = chunk.get("text", "")
                full_answer.append(text)
                yield (
                    f"data: "
                    f"{json.dumps({'type': 'token', 'text': text})}\n\n"
                )
            # blocked
            elif ctype == "blocked":
                final_blocked = True
                yield (
                    f"data: "
                    f"{json.dumps({'type': 'blocked', 'text': chunk.get('text', '')})}\n\n"
                )
            # error
            elif ctype == "error":
                final_blocked = True
                yield (
                    f"data: "
                    f"{json.dumps({'type': 'error', 'text': chunk.get('text', '')})}\n\n"
                )
            # done
            elif ctype == "done":
                yield (
                    f"data: "
                    f"{json.dumps({'type': 'done', 'stop_reason': chunk.get('stop_reason', 'end_turn')})}\n\n"
                )
        # Step 7: Save memory + log conversation
        final_text = "".join(full_answer)
        if not final_blocked and final_text:
            try:
                save_memory(actor_id, session_id, question, final_text, clean_sources)
            except Exception as exc:
                logger.error(f"Memory save error: {exc}")

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