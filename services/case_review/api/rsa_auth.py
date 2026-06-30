"""Shared static-key auth for the AI services (server-to-server).

Other teams send one header — ``X-Signature: <key>`` — carrying the shared
secret. We compare it (constant-time) against ``INTERNAL_API_KEY`` from the
root ``.env``. Match -> request proceeds; mismatch/missing -> 401.

No signing, no timestamp: the header value IS the key. Identity is synthetic —
a valid key proves the caller is a trusted internal team, not which tenant/user.

This file is copied verbatim across doc_service, casenote_monthly,
shift-summary, ai-communication-log and case_review (no shared importable pkg).
"""
from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

_HEADER = "X-Signature"
_ENV_VAR = "INTERNAL_API_KEY"


def _expected_key() -> str:
    return os.environ.get(_ENV_VAR, "").strip()


async def verify_rsa(request: Request) -> None:
    """FastAPI dependency — raises 401 unless the X-Signature key matches."""
    expected = _expected_key()
    if not expected:
        raise HTTPException(status_code=503, detail=f"{_ENV_VAR} not configured")
    provided = request.headers.get(_HEADER, "")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail=f"Invalid or missing {_HEADER}")


# ── case_review-specific: hand back a synthetic AuthContext ───────────────────
# analyze / shift-analysis pass tenant_id into run_pipeline, so they need an
# AuthContext. The key proves a trusted internal caller; tenant is synthetic.
from uuid import UUID  # noqa: E402

from models.schemas import AuthContext  # noqa: E402


async def verify_rsa_auth(request: Request) -> AuthContext:
    """FastAPI dependency: verify X-Signature key, return a synthetic AuthContext."""
    await verify_rsa(request)
    return AuthContext(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        roles=["signature-verified"],
    )
