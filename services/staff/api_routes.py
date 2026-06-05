"""Route handlers: /auth/login, /query/stream, /health.

Each handler extracts RequestContext and delegates to business logic.
"""
import logging
import uuid
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, Header
from fastapi.responses import StreamingResponse
import jwt

from api_context import RequestContext, set_request_context, require_request_context
from api_streaming import generate_stream

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Auth Setup (used by login route)
# ────────────────────────────────────────────────────────────────────────────

def _load_users(users_file: str) -> dict:
    """Load fake_users.json and index by login_id (lowercase)."""
    try:
        with open(users_file) as f:
            data = json.load(f)
        return {
            u["login_id"].lower(): u
            for u in data.get("users", [])
        }
    except FileNotFoundError:
        logger.warning(f"Users file not found: {users_file}")
        return {}
    except Exception as exc:
        logger.error(f"Failed to load users file: {exc}")
        return {}


def _mint_token(user: dict, jwt_secret: str, jwt_algorithm: str, token_ttl: int) -> str:
    """Create signed JWT for user."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user["user_id"],
            "user_id": user["user_id"],
            "org_id": user["org_id"],
            "role": user["role"],
            "full_name": user.get("full_name", ""),
            "login_id": user["login_id"],
            "iat": now,
            "exp": now + timedelta(seconds=token_ttl),
        },
        jwt_secret,
        algorithm=jwt_algorithm,
    )


# ────────────────────────────────────────────────────────────────────────────
# Route Handlers
# ────────────────────────────────────────────────────────────────────────────

async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


async def login(
    login_id: str,
    password: str,
    users_file: str,
    jwt_secret: str,
    jwt_algorithm: str,
    token_ttl: int,
):
    """Validate credentials, return signed JWT.

    Args:
        login_id: Username (case-insensitive)
        password: Raw password
        users_file: Path to fake_users.json
        jwt_secret: Secret for signing
        jwt_algorithm: JWT algorithm (default HS256)
        token_ttl: Token lifetime in seconds

    Returns:
        {"token": "...", "user_id": "...", ...}

    Raises:
        HTTPException(401) if credentials invalid
        HTTPException(403) if account inactive
    """
    users = _load_users(users_file)
    user = users.get(login_id.lower().strip())

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("active", False):
        raise HTTPException(status_code=403, detail="Account is inactive")
    if user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _mint_token(user, jwt_secret, jwt_algorithm, token_ttl)
    logger.info(f"Login OK | user={user['user_id']} org={user['org_id']} role={user['role']}")

    return {
        "token": token,
        "user_id": user["user_id"],
        "org_id": user["org_id"],
        "role": user["role"],
        "full_name": user.get("full_name", ""),
        "login_id": user["login_id"],
    }


async def query_stream(
    question: str,
    session_id: Optional[str],
    session_title: Optional[str],
    is_new_chat: bool,
    query_handler,  # async function(ctx, question) → AsyncGenerator[event]
):
    """Stream a question response as SSE events.

    Args:
        question: User question
        session_id: Optional session ID (generated if not provided)
        session_title: Optional title (defaults to question[:60])
        is_new_chat: Whether this starts a new conversation
        query_handler: Async function that processes the question

    Returns:
        StreamingResponse with SSE events
    """
    ctx = require_request_context()

    # Assign IDs
    session_id = session_id or str(uuid.uuid4())
    session_title = session_title or question[:60]
    question = question.strip()

    logger.info(
        f"Stream query | user={ctx.user_id} org={ctx.org_id} "
        f"session={session_id} q_len={len(question)}"
    )

    # Create async generator for SSE events
    async def event_generator():
        # Initial metadata
        yield f"data: {json.dumps({'type': 'meta', 'session_id': session_id, 'title': session_title})}\n\n"

        try:
            # Call query handler (should yield events)
            async for event in query_handler(ctx, question):
                if isinstance(event, dict):
                    yield f"data: {json.dumps(event)}\n\n"
                else:
                    yield event

            # Done event
            yield f"data: {json.dumps({'type': 'done', 'stop_reason': 'end_turn'})}\n\n"

        except Exception as e:
            logger.exception(f"Query stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def query_json(
    question: str,
    session_id: Optional[str],
    session_title: Optional[str],
    is_new_chat: bool,
    query_handler,  # async function(ctx, question) → dict
):
    """Non-streaming JSON response for a question.

    Args:
        question: User question
        session_id: Optional session ID (generated if not provided)
        session_title: Optional title
        is_new_chat: Whether this starts a new conversation
        query_handler: Async function that processes the question

    Returns:
        {"response": "...", "session_id": "...", ...}
    """
    ctx = require_request_context()

    session_id = session_id or str(uuid.uuid4())
    session_title = session_title or question[:60]
    question = question.strip()

    logger.info(
        f"Query JSON | user={ctx.user_id} org={ctx.org_id} "
        f"session={session_id} q_len={len(question)}"
    )

    try:
        result = await query_handler(ctx, question)
        return {
            "session_id": session_id,
            "title": session_title,
            "response": result,
        }
    except Exception as e:
        logger.exception(f"Query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
