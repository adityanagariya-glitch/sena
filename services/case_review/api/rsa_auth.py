"""RSA signature auth for the AI services (server-to-server).

Callers sign requests with their private key; we verify with their public key
(which we have configured locally as AI_SERVICE_PUBLIC_KEY). If the signature
is valid, the caller is trusted — no per-user JWT is needed.

Signature scheme:
  POST/PUT: sign the request body (bytes)
  GET/DELETE: sign canonical string f"METHOD /path?query"

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
from uuid import UUID

_PUBLIC_KEY = None


def _public_key():
    global _PUBLIC_KEY
    if _PUBLIC_KEY is None:
        raw = os.environ.get("AI_SERVICE_PUBLIC_KEY", "").replace("\\n", "\n").strip()
        if not raw:
            return None  # Signature auth disabled
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


# ── case_review-specific: hand back a synthetic AuthContext ───────────────────
# analyze / shift-analysis pass tenant_id into run_pipeline, so they need an
# AuthContext. The key proves a trusted internal caller; tenant is synthetic.
from models.schemas import AuthContext  # noqa: E402


async def verify_rsa_auth(request: Request) -> AuthContext:
    """FastAPI dependency: verify X-AI-Signature, return a synthetic AuthContext."""
    await verify_rsa(request)
    return AuthContext(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        roles=["signature-verified"],
    )
