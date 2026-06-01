"""Dual authentication: JWT validation + login_user integration.

Validates JWT tokens from Authorization headers and integrates with
the policy service's user management (from memory.py login_user).
"""
import logging
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import jwt

logger = logging.getLogger(__name__)

# Config from env
JWT_SECRET = os.environ.get("JWT_SECRET", "sena-local-qa-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
TOKEN_TTL = 3600  # seconds


def decode_token(authorization: str) -> Dict[str, Any]:
    """Decode and validate JWT token from Authorization header.

    Args:
        authorization: "Bearer <token>" from Authorization header

    Returns:
        Decoded JWT claims dict

    Raises:
        ValueError: If token is malformed, expired, or invalid
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise ValueError("Missing or malformed Authorization header")

    token = authorization.split(" ", 1)[1]

    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"Invalid token: {exc}")

    # Validate required claims
    if not claims.get("org_id"):
        raise ValueError("Token missing org_id claim")
    if not claims.get("user_id"):
        raise ValueError("Token missing user_id claim")
    if not claims.get("role"):
        raise ValueError("Token missing role claim")

    return claims


def mint_token(user: Dict[str, Any]) -> str:
    """Create signed JWT for user.

    Args:
        user: Dict with user_id, org_id, role, full_name, login_id

    Returns:
        Signed JWT token string
    """
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
            "exp": now + timedelta(seconds=TOKEN_TTL),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def load_users(users_file: Optional[str] = None) -> Dict[str, Any]:
    """Load users from JSON file (defaults to fake_users.json).

    Args:
        users_file: Path to JSON users file (default env SENA_USERS_FILE)

    Returns:
        Dict of users indexed by login_id (lowercase)
    """
    if not users_file:
        users_file = os.environ.get(
            "SENA_USERS_FILE",
            os.path.join(os.path.dirname(__file__), "..", "fake_users.json"),
        )

    try:
        with open(users_file) as f:
            data = json.load(f)
        return {u["login_id"].lower(): u for u in data.get("users", [])}
    except FileNotFoundError:
        logger.warning(f"Users file not found: {users_file}")
        return {}
    except Exception as exc:
        logger.error(f"Failed to load users: {exc}")
        return {}


def validate_credentials(
    login_id: str, password: str, users_file: Optional[str] = None
) -> Dict[str, Any]:
    """Validate login credentials and return user dict.

    Args:
        login_id: Username (case-insensitive)
        password: Raw password

    Returns:
        User dict (user_id, org_id, role, etc.)

    Raises:
        ValueError: If credentials invalid or account inactive
    """
    users = load_users(users_file)
    user = users.get(login_id.lower().strip())

    if not user:
        raise ValueError("Invalid credentials")
    if not user.get("active", False):
        raise ValueError("Account is inactive")
    if user.get("password") != password:
        raise ValueError("Invalid credentials")

    return user
