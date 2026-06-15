"""
auth.py
-------
JWT validation dependency for FastAPI routes.

We do NOT issue tokens — the auth server (owned by the mobile team) does that.
This module only verifies that an incoming Bearer token was signed by that server
and has not expired.

Usage in a route:
    from scripts.auth import verify_jwt

    @app.post("/extract")
    def extract(req: ExtractionRequest, payload: dict = Depends(verify_jwt)):
        ...
"""

import logging

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from scripts.config import config

logger = logging.getLogger(__name__)

# FastAPI built-in scheme — reads the "Authorization: Bearer <token>" header.
# auto_error=False lets us return a custom 401 instead of FastAPI's default 403.
_bearer_scheme = HTTPBearer(auto_error=False)


def verify_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """
    FastAPI dependency that validates the incoming JWT.

    Returns the decoded token payload on success.
    Raises HTTP 401 on any failure (missing header, bad signature, expired, etc.).

    Set JWT_ENABLED=false in .env to bypass validation during local development.
    """
    if not config.jwt.enabled:
        logger.warning("JWT validation is DISABLED (JWT_ENABLED=false). Do not use in production.")
        return {}

    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header missing.")

    token = credentials.credentials

    secret = config.jwt.secret_key
    if not secret:
        logger.error("JWT_SECRET_KEY is not configured. Cannot validate tokens.")
        raise HTTPException(status_code=500, detail="Server authentication is not configured.")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[config.jwt.algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidTokenError as exc:
        logger.debug("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token.")

    return payload
