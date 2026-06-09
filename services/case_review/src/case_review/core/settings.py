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
    ai_db_url: str = "postgresql+asyncpg://sena_ai:sena_ai@localhost:5433/sena_ai"

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
    # SENA_AI_GEMINI_MODEL_ID — standard generate_content model (NOT Live API)
    # gemini-3-flash-preview is the current standard model; gemini-3.1-flash-live-preview
    # is Live API only (BidiGenerateContent WebSocket) and cannot be used here.
    gemini_model_id: str = "gemini-3-flash-preview"
    # SENA_AI_GEMINI_REGION — Australian data residency requirement
    gemini_region: str = "australia-southeast1"

    # ── Voice case-note dictation (Gemini Live + dedicated Redis) ─────────────
    # SENA_AI_CASE_REVIEW_REDIS_URL — DEDICATED case_review Redis instance.
    # Distinct env var (NOT SENA_AI_REDIS_URL, which onboarding owns) so the two
    # services use SEPARATE instances; the sena:case_review:{tenant} key prefix
    # isolates data as defense-in-depth. Local host dev → localhost:6380; in
    # docker → redis://case-review-redis:6379/0.
    case_review_redis_url: str = "redis://localhost:6380/0"
    # SENA_AI_GEMINI_LIVE_MODEL_ID — Live API model (WebSocket BidiGenerateContent).
    # Distinct from gemini_model_id above (standard generate_content).
    gemini_live_model_id: str = "gemini-3.1-flash-live-preview"
    # SENA_AI_APP_WEBHOOK_URL / SECRET — mobile-proxy finalize_note delivery target
    # (app backend persists the finished note; this service writes nothing).
    app_webhook_url: str = ""
    app_webhook_secret: str = ""
    # Voice session tuning (mirror onboarding defaults)
    screen_state_max_bytes: int = 8192
    voice_session_max_sec: int = 3600
    voice_silence_timeout_sec: int = 8
    voice_grounding_enabled: bool = False

    # ── Auth ──────────────────────────────────────────────────────────────────
    # SENA_AI_AUTH_MODE: "dev_header" | "jwt"
    auth_mode: str = "dev_header"


settings = CaseReviewSettings()
