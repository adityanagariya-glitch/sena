"""JWT token caching and validation for inter-service calls.

Caches tokens, handles refresh, validates expiration.
"""
import logging
import time
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
import jwt

logger = logging.getLogger(__name__)

# Token cache: {(user_id, org_id): (token_string, exp_time)}
_token_cache: Dict[Tuple[str, str], Tuple[str, float]] = {}

# Config
CACHE_CLEANUP_INTERVAL = 3600  # seconds (clean expired tokens hourly)
_last_cleanup = time.time()


async def cache_token(token: str, user_id: str, org_id: str) -> None:
    """Store token in cache with expiration tracking.

    Args:
        token: JWT token string
        user_id: User ID from claims
        org_id: Org ID from claims
    """
    try:
        # Decode to get expiration (don't verify, just read exp claim)
        payload = jwt.decode(token, options={"verify_signature": False})
        exp_time = payload.get("exp", time.time() + 3600)
    except Exception as e:
        logger.warning(f"Failed to extract token exp: {e}")
        exp_time = time.time() + 3600  # fallback: 1 hour

    key = (user_id, org_id)
    _token_cache[key] = (token, exp_time)
    logger.debug(f"Token cached for {user_id}/{org_id}")


async def get_cached_token(user_id: str, org_id: str) -> Optional[str]:
    """Retrieve cached token if not expired.

    Args:
        user_id: User ID
        org_id: Org ID

    Returns:
        Token string if valid and not expired, else None
    """
    global _last_cleanup

    # Periodically clean up expired tokens
    now = time.time()
    if now - _last_cleanup > CACHE_CLEANUP_INTERVAL:
        _token_cache.clear()  # Simple: just clear all (can be more granular)
        _last_cleanup = now
        logger.debug("Token cache cleared (periodic cleanup)")

    key = (user_id, org_id)
    if key not in _token_cache:
        return None

    token, exp_time = _token_cache[key]
    if now >= exp_time:
        del _token_cache[key]
        logger.debug(f"Token expired for {user_id}/{org_id}")
        return None

    return token


async def validate_token_claims(
    token: str, required_claims: list = None
) -> bool:
    """Validate token has required claims without verifying signature.

    Args:
        token: JWT token
        required_claims: List of claim names to check (default: user_id, org_id)

    Returns:
        True if all required claims present
    """
    required_claims = required_claims or ["user_id", "org_id"]

    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        return all(claim in payload for claim in required_claims)
    except Exception as e:
        logger.warning(f"Token validation failed: {e}")
        return False


async def extract_claims(token: str) -> Dict:
    """Extract JWT claims without signature verification.

    Args:
        token: JWT token

    Returns:
        Claims dict (user_id, org_id, role, exp, etc.)
    """
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception as e:
        logger.warning(f"Failed to extract claims: {e}")
        return {}
