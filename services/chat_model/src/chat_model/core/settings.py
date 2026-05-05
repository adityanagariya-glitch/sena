from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SENA_AI_", case_sensitive=False)

    # Service config
    chat_model_port: int = Field(default=8085, alias="CHAT_MODEL_PORT")
    redis_url: str = Field(alias="REDIS_URL")
    ai_db_url: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5433/ai_db", alias="AI_DB_URL")
    data_path: str = Field(default="data/", alias="DATA_PATH")
    # LLM config
    gemini_api_key: str = Field(alias="GEMINI_API_KEY")
    gemini_model_id: str = Field(default="gemini-3.1-flash-live-preview", alias="GEMINI_MODEL_ID")

    # Data residency (Australia)
    gcp_project_id: str = Field(default="", alias="GCP_PROJECT_ID")
    gcp_region: str = Field(default="australia-southeast1", alias="GCP_REGION")
    gcp_credentials_path: str = Field(default="", alias="GCP_CREDENTIALS_PATH")
    use_vertex_ai: bool = Field(default=True, alias="USE_VERTEX_AI")

    # Authentication & Authorization
    auth_mode: str = Field(default="dev_header", alias="AUTH_MODE")
    jwt_issuer: str | None = Field(default=None, alias="JWT_ISSUER")
    jwt_audience: str | None = Field(default=None, alias="JWT_AUDIENCE")
    jwt_public_key_pem: str | None = Field(default=None, alias="JWT_PUBLIC_KEY_PEM")

    # CORS allowlist
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000"],
        alias="CORS_ALLOWED_ORIGINS",
    )

    # Rate limiting (per user)
    rate_limit_per_minute: int = Field(default=20, alias="RATE_LIMIT_PER_MINUTE")

    # Session config
    redis_session_ttl_seconds: int = Field(default=86400, alias="REDIS_SESSION_TTL_SECONDS")

    # PII detection config (Phase: Compliance)
    pii_detection_enabled: bool = Field(default=False, alias="PII_DETECTION_ENABLED")
    pii_action: str = Field(default="reject", alias="PII_ACTION")

    # Cost control config (Phase: Compliance)
    cost_tokens_per_tenant_per_day: int = Field(default=100000, alias="COST_TOKENS_PER_TENANT_PER_DAY")
    cost_token_warning_threshold: float = Field(default=0.8, alias="COST_TOKEN_WARNING_THRESHOLD")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


settings = Settings()
