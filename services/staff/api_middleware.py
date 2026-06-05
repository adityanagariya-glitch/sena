"""AuthMiddleware: JWT validation and RequestContext setup."""
import logging
import uuid
from typing import Callable

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import jwt

from api_context import RequestContext, set_request_context, clear_request_context

logger = logging.getLogger(__name__)

# These paths bypass auth check
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate JWT token, extract claims, set RequestContext."""

    def __init__(self, app, jwt_secret: str, jwt_algorithm: str = "HS256"):
        """Initialize middleware with JWT config.

        Args:
            app: FastAPI/Starlette application
            jwt_secret: JWT signing secret
            jwt_algorithm: Algorithm (default HS256)
        """
        super().__init__(app)
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Intercept request, validate JWT, set context, pass to handler."""
        # Public paths skip auth
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Extract Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

        token = auth_header.split(" ", 1)[1]

        try:
            # Decode JWT
            claims = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

        # Validate required claims
        if not claims.get("org_id"):
            raise HTTPException(status_code=401, detail="Token missing org_id claim")
        if not claims.get("user_id"):
            raise HTTPException(status_code=401, detail="Token missing user_id claim")
        if not claims.get("role"):
            raise HTTPException(status_code=401, detail="Token missing role claim")

        # Create and store request context
        ctx = RequestContext(
            user_id=claims["user_id"],
            org_id=claims["org_id"],
            role=claims["role"],
            jwt_token=token,
            request_id=str(uuid.uuid4()),
        )
        set_request_context(ctx)
        logger.info(f"Auth OK: {ctx}")

        # Call handler
        response = await call_next(request)

        # Cleanup
        clear_request_context()

        return response
