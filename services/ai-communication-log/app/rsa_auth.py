"""RSA request-signature auth (server-to-server) — single-header scheme.

Matches the existing ``/v1/restrictive-practices/evaluate`` style: the caller
signs with its RSA private key and sends ONE header, ``X-Signature``. This
service verifies with the public key (``AI_SERVICE_PUBLIC_KEY``).

  algorithm  : RSA PKCS#1 v1.5 + SHA-256
  signed msg : POST/PUT/PATCH -> raw request body bytes
               GET/DELETE      -> f"{METHOD} {path}?{sorted_query}" using the
                                  SERVICE-INTERNAL path (no gateway/nginx prefix
                                  such as ``/doc-service``)
  header     : X-Signature  (base64 signature)

Replaces JWT on the wired endpoints. Identity is synthetic — a valid signature
proves the caller is the trusted platform, not which tenant/user.

NOTE: no timestamp / replay window (kept simple to mirror /evaluate). The
channel relies on the secrecy of the private key. Re-add a timestamp header if
replay protection becomes a requirement.

This file is copied verbatim across doc_service, casenote_monthly,
shift-summary, ai-communication-log and case_review (no shared importable pkg).
"""
from __future__ import annotations

import base64
import os
from urllib.parse import parse_qsl, urlencode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import HTTPException, Request

_PUBLIC_KEY = None


def _public_key():
    """Load + cache the verifying public key. Handles the docker ``\\n`` gotcha."""
    global _PUBLIC_KEY
    if _PUBLIC_KEY is None:
        raw = os.environ.get("AI_SERVICE_PUBLIC_KEY", "").replace("\\n", "\n").strip()
        if not raw:
            raise HTTPException(status_code=503, detail="AI_SERVICE_PUBLIC_KEY not configured")
        _PUBLIC_KEY = serialization.load_pem_public_key(raw.encode())
    return _PUBLIC_KEY


def _signed_message(request: Request, body: bytes) -> bytes:
    """Bytes the signature must cover: body for writes, canonical line for reads."""
    method = request.method.upper()
    if method in ("GET", "DELETE", "HEAD"):
        query = urlencode(sorted(parse_qsl(request.url.query)))
        canonical = f"{method} {request.url.path}"
        if query:
            canonical += f"?{query}"
        return canonical.encode()
    return body


async def verify_rsa(request: Request) -> None:
    """FastAPI dependency — raises 401 unless ``X-Signature`` is valid."""
    sig_b64 = request.headers.get("X-Signature")
    if not sig_b64:
        raise HTTPException(status_code=401, detail="Missing X-Signature header")

    body = b""
    if request.method.upper() in ("POST", "PUT", "PATCH"):
        # Starlette caches the body, so downstream body/form parsing still works.
        body = await request.body()
    message = _signed_message(request, body)

    try:
        signature = base64.b64decode(sig_b64)
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed X-Signature encoding")

    try:
        _public_key().verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid request signature")
