"""RSA signature auth for the AI services (server-to-server).

Callers sign requests with their private key; we verify with their public key
(which we have configured locally as AI_SERVICE_PUBLIC_KEY). If the signature
is valid, the caller is trusted — no per-user JWT is needed.

Signature scheme (ALL methods — GET/POST/PUT/DELETE):
  sign the canonical request line: f"METHOD /path?query"
  The BODY is NOT signed (verifying it would consume the stream before
  FastAPI parses it).
  IMPORTANT: /path is the SERVICE-INTERNAL path. nginx strips the
  /<service>/ prefix before the request reaches the app, so sign e.g.
  "/v1/restrictive-practices/incidents/analyze" — NOT
  "/case-review/v1/restrictive-practices/incidents/analyze".

Both use RSA PKCS#1 v1.5 + SHA-256, with headers:
  X-AI-Signature: base64(sig)
  X-AI-Timestamp: unix timestamp (optional, not validated)

If AI_SERVICE_PUBLIC_KEY is blank, signature auth is disabled (request passes).
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import HTTPException, Request

_PUBLIC_KEY = None


def _public_key():
    global _PUBLIC_KEY
    if _PUBLIC_KEY is None:
        raw = os.environ.get("AI_SERVICE_PUBLIC_KEY", "").strip()
        if not raw:
            return None  # Signature auth disabled
        # Handle both literal \n (from .env) and real newlines
        raw = raw.replace("\\n", "\n")
        _PUBLIC_KEY = serialization.load_pem_public_key(raw.encode())
    return _PUBLIC_KEY


async def verify_rsa(request: Request) -> None:
    """FastAPI dependency — verify X-AI-Signature or raise 401.

    Signature covers the canonical request line (method + path + query),
    NOT the body — this avoids consuming the body before FastAPI parses it.

    Canonical message: "METHOD /path?query"
    """
    pub_key = _public_key()
    if not pub_key:
        return  # No public key configured; auth disabled

    sig_b64 = request.headers.get("X-AI-Signature", "")
    if not sig_b64:
        raise HTTPException(status_code=401, detail="Missing X-AI-Signature")

    # Reconstruct the canonical request line (method + path + optional query)
    path = request.url.path
    query = request.url.query
    message = f"{request.method} {path}{'?' + query if query else ''}".encode()

    # Verify the signature
    try:
        sig = base64.b64decode(sig_b64)
        pub_key.verify(sig, message, padding.PKCS1v15(), hashes.SHA256())
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Signature verification failed: {e}")


from uuid import UUID  # noqa: E402
from models.schemas import AuthContext  # noqa: E402


async def verify_rsa_auth(request: Request) -> AuthContext:
    """FastAPI dependency: verify X-AI-Signature, return a synthetic AuthContext."""
    await verify_rsa(request)
    return AuthContext(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        roles=["signature-verified"],
    )
