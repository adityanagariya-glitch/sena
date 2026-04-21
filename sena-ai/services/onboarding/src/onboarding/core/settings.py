from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class OnboardingSettings(BaseSettings):
    """
    All env vars read as SENA_AI_<FIELD_NAME_UPPER>.
    No Field(alias=...) — aliases bypass env_prefix in pydantic-settings.
    """

    # env_file list: checked in order, later entries override earlier.
    # "../../.env" = sena-ai/.env (shared across services) when cwd = sena-ai/services/onboarding
    # ".env" = local override if present
    model_config = SettingsConfigDict(
        env_file=["../../.env", ".env"],
        env_prefix="SENA_AI_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service ───────────────────────────────────────────────────────────────
    # SENA_AI_SERVICE_VERSION
    service_version: str = "0.1.0"
    # SENA_AI_ENVIRONMENT
    environment: str = "development"
    # SENA_AI_DEBUG
    debug: bool = True
    # SENA_AI_HOST
    host: str = "0.0.0.0"
    # SENA_AI_ONBOARDING_PORT
    onboarding_port: int = 8083
    # SENA_AI_LOG_LEVEL
    log_level: str = "INFO"

    # ── Redis ─────────────────────────────────────────────────────────────────
    # SENA_AI_REDIS_URL
    redis_url: str = "redis://localhost:6379"
    # SENA_AI_ONBOARDING_SESSION_TTL_MIN — inactivity timeout, extended each WS message
    onboarding_session_ttl_min: int = 15
    # SENA_AI_ONBOARDING_SESSION_MAX_MIN — hard session cap
    onboarding_session_max_min: int = 60
    # SENA_AI_ONBOARDING_RESUMPTION_TTL_MIN — how long a resumption handle stays valid
    onboarding_resumption_ttl_min: int = 30

    # ── Gemini ────────────────────────────────────────────────────────────────
    # SENA_AI_GEMINI_API_KEY
    gemini_api_key: str = ""
    # SENA_AI_GEMINI_LIVE_MODEL_ID
    gemini_live_model_id: str = "gemini-3.1-flash-live-preview"

    # ── App backend webhook ───────────────────────────────────────────────────
    # SENA_AI_APP_WEBHOOK_URL
    app_webhook_url: str = "https://mock.example.com/webhooks/sena"
    # SENA_AI_APP_WEBHOOK_SECRET
    app_webhook_secret: str = ""
    # SENA_AI_ONBOARDING_WEBHOOK_MAX_RETRIES
    onboarding_webhook_max_retries: int = 3

    # ── Feature flags ─────────────────────────────────────────────────────────
    # SENA_AI_ONBOARDING_GROUNDING_ENABLED
    onboarding_grounding_enabled: bool = True
    # SENA_AI_ONBOARDING_FRAME_FPS_LIMIT
    onboarding_frame_fps_limit: int = 2

    # ── Derived (seconds) ─────────────────────────────────────────────────────
    @property
    def session_ttl_sec(self) -> int:
        return self.onboarding_session_ttl_min * 60

    @property
    def session_max_sec(self) -> int:
        return self.onboarding_session_max_min * 60

    @property
    def resumption_ttl_sec(self) -> int:
        return self.onboarding_resumption_ttl_min * 60


settings = OnboardingSettings()
