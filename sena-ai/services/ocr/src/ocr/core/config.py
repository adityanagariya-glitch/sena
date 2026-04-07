"""OCR service configuration."""

from __future__ import annotations

from functools import lru_cache

from sena_common.config.settings import Settings


class OCRSettings(Settings):
    """OCR-specific settings."""

    service_name: str = "sena-ocr"

    # OCR processing (populated after cloud provider decision)
    max_file_size_mb: int = 10
    supported_formats: list[str] = ["image/jpeg", "image/png", "application/pdf"]
    confidence_threshold: float = 0.7


@lru_cache
def get_settings() -> OCRSettings:
    return OCRSettings()
