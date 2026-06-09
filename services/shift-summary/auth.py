import hmac
from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
from config import get_settings

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    """
    FastAPI dependency that validates the X-API-Key header.
    Uses hmac.compare_digest for constant-time comparison to prevent timing attacks.
    """
    settings = get_settings()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
        )

    # Constant-time comparison — safe against timing attacks
    if not hmac.compare_digest(api_key.encode(), settings.api_key.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    return api_key
