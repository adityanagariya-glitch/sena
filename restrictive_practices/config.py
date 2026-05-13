from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENA_AI_",
        env_file=str(_ENV_FILE),
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

    # Database
    rp_database_url: str = "postgresql+asyncpg://sena_ai:sena_ai@localhost:5433/sena_ai"

    # Embedding model (Bedrock)
    embedding_model: str = "cohere.embed-english-v3"

    # Chunking
    chunk_size: int = 1200
    chunk_overlap: int = 120

    # LLM models (Bedrock — Claude)
    triage_model: str = "anthropic.claude-haiku-4-5-20251001-v1:0"
    evaluator_model: str = "anthropic.claude-sonnet-4-6-v1:0"

    # RAG
    rag_top_k: int = 5

    # Webhook
    rp_webhook_url: str = ""
    rp_webhook_secret: str = ""  # HMAC-SHA256 signing key; leave blank to skip signing


settings = Settings()
