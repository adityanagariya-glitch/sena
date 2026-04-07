# OCR Service Configuration (services/ocr/src/ocr/core/config.py)
#
# Purpose: OCR service-specific settings
#
# Class: OCRSettings (extends Settings)
# Inherits all base settings from sena_common.config.settings.Settings
#
# OCR-specific configuration:
# - service_name: "sena-ocr" (override from base)
#   Identifies this service in logs and headers
#
# - max_file_size_mb: 10 MB
#   Maximum file upload size
#   Env: SENA_MAX_FILE_SIZE_MB
#
# - supported_formats: List of MIME types
#   ["image/jpeg", "image/png", "application/pdf"]
#   Env: SENA_SUPPORTED_FORMATS (comma-separated)
#
# - confidence_threshold: 0.7 (70%)
#   Minimum OCR confidence for accepting extracted text
#   Env: SENA_CONFIDENCE_THRESHOLD
#
# Function: get_settings()
# - Decorated with @lru_cache
# - Returns singleton OCRSettings instance
# - Safe for repeated calls (settings don't change during runtime)
#
# Usage:
# settings = get_settings()
# max_size = settings.max_file_size_mb
# supported = settings.supported_formats
