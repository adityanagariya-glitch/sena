# Application Settings (shared/src/sena_common/config/settings.py)
#
# Purpose: Pydantic BaseSettings model for application configuration
#
# Settings (read from environment with SENA_ prefix):
#
# Database:
# - database_url: PostgreSQL connection string (async SQLAlchemy URL)
#   Default: postgresql+asyncpg://sena_app:localdev@localhost:5432/sena_ai
#   Env: SENA_DATABASE_URL
#
# Environment:
# - environment: deployment environment (development | staging | production)
#   Default: development
#   Env: SENA_ENVIRONMENT
#
# - debug: Enable debug mode
#   Default: False
#   Env: SENA_DEBUG
#
# Service info (overridden in service-specific settings):
# - service_name: Service identifier
#   Default: sena-ai
#   Env: SENA_SERVICE_NAME
#
# - service_version: Semantic version
#   Default: 0.1.0
#   Env: SENA_SERVICE_VERSION
#
# Logging:
# - log_level: INFO, DEBUG, WARNING, ERROR, CRITICAL
#   Default: INFO
#   Env: SENA_LOG_LEVEL
#
# - log_format: json or text
#   Default: json
#   Env: SENA_LOG_FORMAT
#
# Model config:
# - env_prefix: SENA_ (all env vars must start with this)
# - case_sensitive: False (SENA_DATABASE_URL or sena_database_url both work)
#
# Usage:
# settings = Settings()  # Reads from environment
# print(settings.database_url)
