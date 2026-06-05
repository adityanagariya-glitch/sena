"""
Authentication for ai_chatbot gateway.

TEMPORARY FOR TESTING:
- Supports email/password login (calls real API)
- Supports JWT token login

PRODUCTION:
- Remove email/password login
- Use JWT-only authentication
- Users authenticate via real auth service, get JWT, use JWT here

This matches staff folder authentication pattern but adds JWT support.
"""
import requests
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Real API endpoint (same as staff)
API_BASE_URL = "https://dev-api.isena.org/api"

# Global token storage
_token = None
_user_context = {}
_last_error = None


def get_last_error() -> Optional[str]:
    """Return the human-readable reason the last auth attempt failed (or None)."""
    return _last_error


def get_token() -> Optional[str]:
    """Get current JWT token."""
    return _token


def get_user_context() -> Dict:
    """Get current user context."""
    return _user_context.copy()


def login_user(email: str, password: str) -> bool:
    """
    Login with email and password using the real API.

    Args:
        email: User email
        password: User password

    Returns:
        True if successful, False otherwise
    """
    global _token, _user_context, _last_error
    _last_error = None

    logger.info(f"[AUTH] Authenticating {email}...")

    try:
        login_payload = {
            "email": email,
            "password": password,
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://dev-api.isena.org",
            "Referer": "https://dev-api.isena.org/",
        }

        response = requests.post(
            f"{API_BASE_URL}/auth/ai/login",
            json=login_payload,
            headers=headers,
            timeout=15,
        )

        logger.info(f"[AUTH] API Response: {response.status_code}")

        if response.status_code == 200:
            login_data = response.json()

            # Response shape: { "data": { "accessToken": "...", "user": {...} } }
            data = login_data.get("data", {}) or {}
            _token = data.get("accessToken") or data.get("access_token") or data.get("token")

            if _token:
                user = data.get("user") or {}
                default_ctx = data.get("defaultContext") or {}

                # Store user context
                _user_context = {
                    "user_id": user.get("id") or default_ctx.get("userId"),
                    "email": user.get("email") or email,
                    "organization_id": default_ctx.get("organizationId"),
                    "user_type": user.get("userType", {}).get("type", "").lower() if isinstance(user.get("userType"), dict) else "",
                    "name": user.get("name", ""),
                }

                logger.info(f" [AUTH] Login successful: {email}")
                logger.info(f" [AUTH] User context: {_user_context}")
                return True
            else:
                _last_error = "API returned 200 but no access token was found in the response."
                logger.error("[AUTH] No token in response")
                return False
        else:
            # Surface the real API message (e.g. wrong password, validation error)
            try:
                body = response.json()
                msg = body.get("message") or body.get("error") or response.text
                details = body.get("details")
                if details:
                    msg = f"{msg}: {details}"
            except Exception:
                msg = response.text
            _last_error = f"API {response.status_code}: {msg}"
            logger.error(f"[AUTH] Login failed: {_last_error}")
            return False

    except requests.exceptions.ConnectionError:
        _last_error = f"Cannot connect to API: {API_BASE_URL}"
        logger.error(f"[AUTH] {_last_error}")
        return False
    except requests.exceptions.Timeout:
        _last_error = "API request timed out."
        logger.error(f"[AUTH] {_last_error}")
        return False
    except Exception as e:
        _last_error = f"{type(e).__name__}: {e}"
        logger.error(f"[AUTH] Login error: {_last_error}")
        return False


def authenticate_with_jwt(token: str) -> bool:
    """
    Authenticate with a JWT token directly.

    Args:
        token: JWT token string

    Returns:
        True if valid, False otherwise
    """
    global _token, _user_context

    logger.info(f"[AUTH] Validating JWT token...")

    if not token:
        logger.error("[AUTH] No token provided")
        return False

    try:
        # Store the token (in production, should validate the signature)
        _token = token
        _user_context = {
            "token_source": "direct_jwt",
        }

        logger.info(f"[AUTH] JWT token accepted")
        return True

    except Exception as e:
        logger.error(f"[AUTH] JWT validation error: {e}")
        return False


def logout():
    """Clear authentication."""
    global _token, _user_context
    _token = None
    _user_context = {}
    logger.info("[AUTH] Logged out")
