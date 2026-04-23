from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CaseReviewSettings(BaseSettings):
    """
    All env vars read as SENA_AI_<FIELD_NAME_UPPER>.
    env_file hierarchy: sena-ai/.env (shared) → local .env (override).
    """

    model_config = SettingsConfigDict(
        env_file=["../../.env", ".env"],
        env_prefix="SENA_AI_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service ───────────────────────────────────────────────────────────────
    service_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    # SENA_AI_CASE_REVIEW_PORT
    case_review_port: int = 8084
    log_level: str = "INFO"

    # ── Database (ai-db, pgvector, port 5433) ─────────────────────────────────
    # SENA_AI_AI_DB_URL — asyncpg driver
    ai_db_url: str = "postgresql+asyncpg://sena_app:sena_pass@localhost:5433/sena_ai"

    # ── External: other engineer's drafting service ───────────────────────────
    # SENA_AI_DRAFTING_SERVICE_URL
    drafting_service_url: str = "http://localhost:8085"
    # SENA_AI_DRAFTING_SERVICE_API_KEY
    drafting_service_api_key: str = ""
    # SENA_AI_CASE_NOTE_FETCH_LIMIT — how many past notes to fetch for context
    case_note_fetch_limit: int = 10

    # ── Gemini ────────────────────────────────────────────────────────────────
    # SENA_AI_GEMINI_API_KEY
    gemini_api_key: str = ""
    # SENA_AI_GEMINI_MODEL_ID — standard (non-live) model for summarise/classify/review
    gemini_model_id: str = "gemini-2.0-flash"
    # SENA_AI_GEMINI_REGION — Australian data residency requirement
    gemini_region: str = "australia-southeast1"

    # ── Auth ──────────────────────────────────────────────────────────────────
    # SENA_AI_AUTH_MODE: "dev_header" | "jwt"
    auth_mode: str = "dev_header"


settings = CaseReviewSettings()
