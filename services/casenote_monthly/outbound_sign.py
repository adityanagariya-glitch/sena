"""Sign OUTBOUND requests to the SENA platform with our RSA private key.

Mirrors ai_chatbot/conversation_store._sign — the platform already verifies this
scheme with our public key:

  algorithm : RSA PKCS#1 v1.5 + SHA-256
  message   : f"{timestamp}." + body   (body is b"" for GET — only the timestamp
              is signed, which is what /ai/client-data needs)
  headers   : X-AI-Timestamp + X-AI-Signature

Replaces the per-user JWT on downstream calls: the AI service authenticates as
itself (trusted service) instead of forwarding a caller token.
"""
from __future__ import annotations

import base64
import os
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_PRIVATE_KEY = None


def _private_key():
    global _PRIVATE_KEY
    if _PRIVATE_KEY is None:
        raw = os.environ.get("AI_WEBHOOK_PRIVATE_KEY_PEM", "").replace("\\n", "\n").strip()
        if not raw:
            raise RuntimeError("AI_WEBHOOK_PRIVATE_KEY_PEM not configured")
        _PRIVATE_KEY = serialization.load_pem_private_key(raw.encode(), password=None)
    return _PRIVATE_KEY


def sign_headers(body: bytes = b"") -> dict[str, str]:
    """Return X-AI-Timestamp + X-AI-Signature for an outbound request body."""
    ts = str(int(time.time()))
    message = f"{ts}.".encode() + body
    sig = _private_key().sign(message, padding.PKCS1v15(), hashes.SHA256())
    return {
        "X-AI-Timestamp": ts,
        "X-AI-Signature": base64.b64encode(sig).decode(),
    }
