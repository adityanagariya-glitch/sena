"""
config.py
---------
Central configuration for the Document Extraction Module.
All tuneable values live here — no magic strings scattered across the codebase.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BedrockConfig:
    """AWS Bedrock / Nova Lite settings."""

    region: str = field(
        default_factory=lambda: os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")
    )
    model_id: str = field(
        default_factory=lambda: os.environ.get("BEDROCK_MODEL_ID", "us.meta.llama3-2-90b-instruct-v1:0")
    )

    # How many times to retry the Bedrock call on timeout or throttle
    max_retries: int = 2

    # Seconds to wait between retries (simple fixed backoff)
    retry_delay_seconds: float = 1.5

    # Nova Lite inference parameters
    max_tokens: int = 512
    temperature: float = 0.0   # deterministic — we want consistent JSON


@dataclass(frozen=True)
class S3Config:
    """AWS S3 settings for document download."""

    # Set S3_BUCKET_NAME environment variable before running in production.
    # For local testing this is unused — the /extract/local endpoint bypasses S3.
    bucket_name: str = field(
        default_factory=lambda: os.environ.get("S3_BUCKET_NAME", "")
    )

    # S3 region — defaults to same region as Bedrock
    region: str = field(
        default_factory=lambda: os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")
    )


@dataclass(frozen=True)
class DocumentConfig:
    """Supported document format settings."""

    # Accepted file extensions
    supported_extensions: tuple = (".jpg", ".jpeg", ".png", ".pdf", ".docx")


@dataclass(frozen=True)
class ExtractionConfig:
    """Field extraction settings."""

    # The 5 static fields the module always returns
    static_fields: tuple = (
        "document_no",
        "name",
        "issue_date",
        "expiry_date",
        "address",
    )

    # Date format all dates are normalised to
    date_format: str = "YYYY-MM-DD"


@dataclass(frozen=True)
class JWTConfig:
    """JWT validation settings — we verify tokens, we do NOT issue them."""

    # Secret shared with the auth server (HS256) OR path to public key (RS256).
    # Must be set via JWT_SECRET_KEY environment variable before starting the server.
    secret_key: str = field(
        default_factory=lambda: os.environ.get("JWT_SECRET_KEY", "")
    )

    # Signing algorithm used by the auth server. Override with JWT_ALGORITHM env var.
    algorithm: str = field(
        default_factory=lambda: os.environ.get("JWT_ALGORITHM", "HS256")
    )

    # Set JWT_ENABLED=false to skip validation in local development.
    # Always keep true in staging/production.
    enabled: bool = field(
        default_factory=lambda: os.environ.get("JWT_ENABLED", "false").lower() != "false"
    )


@dataclass(frozen=True)
class AppConfig:
    """Top-level config composed of sub-configs."""

    bedrock:    BedrockConfig    = field(default_factory=BedrockConfig)
    s3:         S3Config         = field(default_factory=S3Config)
    document:   DocumentConfig   = field(default_factory=DocumentConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    jwt:        JWTConfig        = field(default_factory=JWTConfig)


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------
config = AppConfig()