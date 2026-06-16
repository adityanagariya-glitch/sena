from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent / ".env"
_ROOT_ENV = Path(__file__).parent.parent / ".env"  # repo-root global .env (shared SENA keys incl. SENA_AI_GEMINI_API_KEY)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENA_AI_",
        env_file=(str(_ROOT_ENV), str(_ENV_FILE)),  # global first; local restrictive_practices/.env overrides if present
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # AWS Bedrock — region for all inference + embedding calls
    aws_region: str = "ap-southeast-2"  # Sydney — AU data residency (APP 8)

    # AWS credentials — read without SENA_AI_ prefix so boto3 standard env vars work in .env
    # Leave blank to fall back to IAM role / ~/.aws/credentials chain
    aws_access_key_id: str = Field(default="", validation_alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="", validation_alias="AWS_SECRET_ACCESS_KEY")

    # S3 credentials — separate key pair for S3 + Transcribe (different account/role from Bedrock)
    # Read without SENA_AI_ prefix. Leave blank to fall back to Bedrock creds above.
    s3_region: str = Field(default="", validation_alias="S3_REGION")
    s3_access_key_id: str = Field(default="", validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(default="", validation_alias="S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field(default="", validation_alias="S3_BUCKET")
    s3_public_base_url: str = Field(default="", validation_alias="S3_PUBLIC_BASE_URL")

    # Database
    rp_database_url: str = "postgresql+asyncpg://sena_ai:sena_ai@localhost:5433/sena_ai"

    # Embedding model (Bedrock)
    embedding_model: str = "cohere.embed-english-v3"

    # Chunking
    chunk_size: int = 1200
    chunk_overlap: int = 120

    # LLM models (Bedrock — Claude)
    triage_model: str = "anthropic.claude-3-haiku-20240307-v1:0"
    evaluator_model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    # RAG
    rag_top_k: int = 5

    # Webhook
    rp_webhook_url: str = ""
    rp_webhook_secret: str = ""  # HMAC-SHA256 signing key; leave blank to skip signing

    # Speech-to-text (Amazon Transcribe — used by POST /draft/audio)
    transcription_bucket: str = ""        # S3 bucket for temp audio; required for /draft/audio
    transcription_language: str = "en-AU" # Transcribe language code
    transcription_vocab_name: str = ""    # Custom vocabulary name (optional; blank = omit)

    # Voice assistant (Gemini Live + Redis)
    gemini_api_key: str = ""
    gemini_live_model_id: str = "gemini-3.1-flash-live-preview"
    redis_url: str = "redis://localhost:6379/0"
    voice_session_max_sec: int = 3600
    voice_silence_timeout_sec: int = 8
    voice_validation_advisory: bool = True
    voice_grounding_enabled: bool = False
    screen_state_max_bytes: int = 8192
    resumption_handle_ttl_sec: int = 600
    debug: bool = False


settings = Settings()
