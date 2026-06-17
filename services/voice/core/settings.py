from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceSettings(BaseSettings):
    # env_file list: checked in order, later entries override earlier.
    # "../../.env" = repo-root .env (shared across services) when cwd = services/voice
    # ".env" = local override if present
    model_config = SettingsConfigDict(
        env_file=["../../.env", ".env"],
        env_prefix="SENA_AI_",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = Field(default="sena-voice", alias="SERVICE_NAME")
    service_version: str = Field(default="0.1.0", alias="SERVICE_VERSION")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=True, alias="DEBUG")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8082, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    auth_mode: str = Field(default="dev_header", alias="AUTH_MODE")
    jwt_issuer: str | None = Field(default=None, alias="JWT_ISSUER")
    jwt_audience: str | None = Field(default=None, alias="JWT_AUDIENCE")
    jwt_public_key_pem: str | None = Field(default=None, alias="JWT_PUBLIC_KEY_PEM")

    ai_db_url: str = Field(alias="AI_DB_URL")
    shared_db_url: str = Field(alias="SHARED_DB_URL")
    redis_url: str = Field(alias="REDIS_URL")
    redis_lock_ttl_seconds: int = Field(default=3600, alias="REDIS_LOCK_TTL_SECONDS")
    redis_session_ttl_seconds: int = Field(default=86400, alias="REDIS_SESSION_TTL_SECONDS")

    aws_region: str = Field(default="ap-southeast-2", alias="AWS_REGION")
    bedrock_model_id: str = Field(
        default="au.anthropic.claude-sonnet-4-6", alias="BEDROCK_MODEL_ID"
    )
    bedrock_max_tokens: int = Field(default=7600, alias="BEDROCK_MAX_TOKENS")
    bedrock_temperature: float = Field(default=0.2, alias="BEDROCK_TEMPERATURE")

    livekit_api_key: str = Field(alias="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(alias="LIVEKIT_API_SECRET")
    livekit_url: str = Field(alias="LIVEKIT_URL")

    sns_case_note_topic_arn: str = Field(alias="SNS_CASE_NOTE_TOPIC_ARN")

    rate_limit_start_per_minute: int = Field(default=30, alias="RATE_LIMIT_START_PER_MINUTE")
    rate_limit_turn_per_minute: int = Field(default=120, alias="RATE_LIMIT_TURN_PER_MINUTE")

    # Timeout for LLM provider calls. For long audio (30 min), Bedrock/Gemini can take
    # 30-60 seconds. Set to 120s to handle long transcripts comfortably.
    provider_timeout_seconds: float = Field(default=120, alias="PROVIDER_TIMEOUT_SECONDS")
    provider_max_retries: int = Field(default=2, alias="PROVIDER_MAX_RETRIES")

    # Voice session max duration (30 minutes = 1800 seconds). Supports long-form dictation.
    voice_session_max_sec: int = Field(default=1800, alias="VOICE_SESSION_MAX_SEC")

    gemini_api_key: str = Field(alias="GEMINI_API_KEY")
    gemini_model_id: str = Field(default="gemini-3.5-flash", alias="GEMINI_MODEL_ID")
    gemini_live_model_id: str = Field(
        default="gemini-2.5-flash-native-audio-latest", alias="GEMINI_LIVE_MODEL_ID"
    )


settings = VoiceSettings()