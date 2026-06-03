"""Stateless JWT auth for the case-note summary service.

service is token-in-header only: the caller passes `Authorization: Bearer <jwt>`,
we decode it locally, check expiry, and forward it as the backend bearer token.
"""
import base64
import json
from datetime import datetime, timezone

from config import API_BASE_URL


def decode_jwt(token: str | None) -> dict | None:
    """Decode a JWT payload (no signature verification — backend enforces that)."""
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None


def validate_jwt(token: str | None) -> tuple[bool, str | None, dict | None]:
    """Validate a bearer token: decodable + not expired.

    Returns (ok, error_message, claims). On success error_message is None.
    """
    if not token:
        return False, "Missing Authorization bearer token", None

    claims = decode_jwt(token)
    if not claims:
        return False, "Could not decode JWT token", None

    exp = claims.get("exp")
    if exp:
        try:
            if datetime.now(timezone.utc) > datetime.fromtimestamp(exp, tz=timezone.utc):
                return False, "JWT token expired", claims
        except (TypeError, ValueError, OSError):
            pass  # malformed exp — let the backend make the final call

    return True, None, claims


def get_auth_headers(token: str) -> dict[str, str]:
    """Build the headers used for every backend API call (mirrors staff/auth.py)."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://dev-api.isena.org",
        "Referer": "https://dev-api.isena.org/",
        "Authorization": f"Bearer {token}",
    }
