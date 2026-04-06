"""Application settings — reads from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Base settings for all Sena AI services.

    All values are read from environment variables. Default values
    are for local development only.
    """

    # Database
    database_url: str = "postgresql+asyncpg://sena_app:localdev@localhost:5432/sena_ai"

    # Environment
    environment: str = "development"  # development | staging | production
    debug: bool = False

    # Service info (overridden per service)
    service_name: str = "sena-ai"
    service_version: str = "0.1.0"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # json | text

    model_config = {"env_prefix": "SENA_", "case_sensitive": False}
