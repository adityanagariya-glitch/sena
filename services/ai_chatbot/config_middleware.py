"""Configuration for middleware, routing, and service integration.

Load from environment variables with sensible defaults.
"""
import os
from typing import Optional

# ────────────────────────────────────────────────────────────────────────────
# Service URLs
# ────────────────────────────────────────────────────────────────────────────

STAFF_API_URL = os.environ.get("STAFF_API_URL", "http://localhost:8001")
POLICY_API_URL = os.environ.get("POLICY_API_URL", "http://localhost:8000")

# ────────────────────────────────────────────────────────────────────────────
# JWT/Auth
# ────────────────────────────────────────────────────────────────────────────

JWT_SECRET = os.environ.get("JWT_SECRET", "sena-local-qa-secret-change-in-prod")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
TOKEN_TTL = int(os.environ.get("TOKEN_TTL", "3600"))  # seconds

# ────────────────────────────────────────────────────────────────────────────
# Circuit Breaker
# ────────────────────────────────────────────────────────────────────────────

CB_FAILURE_THRESHOLD = int(os.environ.get("CB_FAILURE_THRESHOLD", "5"))
CB_RECOVERY_TIMEOUT = float(os.environ.get("CB_RECOVERY_TIMEOUT", "60"))
CB_HALF_OPEN_MAX_CALLS = int(os.environ.get("CB_HALF_OPEN_MAX_CALLS", "1"))

# ────────────────────────────────────────────────────────────────────────────
# Bedrock Classification
# ────────────────────────────────────────────────────────────────────────────

BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-haiku-20240307-v1:0",
)

# ────────────────────────────────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────────────────────────────────

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# ────────────────────────────────────────────────────────────────────────────
# Helper functions
# ────────────────────────────────────────────────────────────────────────────


def get_service_url(service_name: str) -> str:
    """Get configured URL for a service.

    Args:
        service_name: "staff" or "policy"

    Returns:
        Base URL (with trailing slash stripped)
    """
    if service_name == "staff":
        return STAFF_API_URL.rstrip("/")
    elif service_name == "policy":
        return POLICY_API_URL.rstrip("/")
    else:
        raise ValueError(f"Unknown service: {service_name}")
