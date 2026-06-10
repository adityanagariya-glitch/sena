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

    region: str = "ap-southeast-2"
    model_id: str = "amazon.nova-lite-v1:0" #amazon.nova-lite-v1:0

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
        default_factory=lambda: os.environ.get("AWS_REGION", "ap-southeast-2")
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
    date_format: str = "DD/MM/YYYY"


@dataclass(frozen=True)
class AppConfig:
    """Top-level config composed of sub-configs."""

    bedrock:    BedrockConfig    = field(default_factory=BedrockConfig)
    s3:         S3Config         = field(default_factory=S3Config)
    document:   DocumentConfig   = field(default_factory=DocumentConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------
config = AppConfig()