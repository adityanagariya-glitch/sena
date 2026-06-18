from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────
    app_title: str = Field(default="Summary Consolidation API")
    app_version: str = Field(default="1.0.0")
    app_env: str = Field(default="development")

    # ── Security ─────────────────────────────────────────────
    api_key: str = Field(..., description="Secret key required in X-API-Key header")

    # ── AWS / Bedrock ─────────────────────────────────────────
    aws_access_key_id: str = Field(...)
    aws_secret_access_key: str = Field(...)
    aws_region: str = Field(default="ap-southeast-2")

    # ── Bedrock Model ─────────────────────────────────────────
    bedrock_model_id: str = Field(default="au.anthropic.claude-haiku-4-5-20251001-v1:0")
    bedrock_max_tokens: int = Field(default=1024, gt=0, le=8096)
    bedrock_temperature: float = Field(default=0.3, ge=0.0, le=1.0)

    # ── Validation ────────────────────────────────────────────
    min_summaries: int = Field(default=1, gt=0)
    max_summaries: int = Field(default=5, gt=0)
    min_summary_length: int = Field(default=1, gt=0)
    max_summary_length: int = Field(default=5000, gt=0)

    @field_validator("max_summaries")
    @classmethod
    def max_must_exceed_min(cls, v: int, info) -> int:
        min_val = info.data.get("min_summaries", 1)
        if v < min_val:
            raise ValueError(
                f"max_summaries ({v}) must be >= min_summaries ({min_val})"
            )
        return v

    @field_validator("app_env")
    @classmethod
    def valid_env(cls, v: str) -> str:
        allowed = {"development", "production", "test"}
        if v not in allowed:
            raise ValueError(f"app_env must be one of {allowed}")
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — re-instantiated only when cache is cleared."""
    return Settings()