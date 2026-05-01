from pathlib import Path

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

    # Google Cloud — required for Vertex AI mode
    gemini_api_key: str = ""          # AI Studio key (AIzaSy...) — leave blank if using Vertex AI
    gcp_project: str = ""             # GCP project ID — required for Vertex AI
    gcp_location: str = "australia-southeast1"  # NDIS APP 8 — AU data residency mandate

    # Database
    rp_database_url: str = "postgresql+asyncpg://sena_ai:sena_ai@localhost:5433/sena_ai"

    # Embedding model
    embedding_model: str = "text-embedding-004"

    # Chunking
    chunk_size: int = 1200
    chunk_overlap: int = 120

    # LLM models (Gemini)
    triage_model: str = "gemini-2.5-flash"
    evaluator_model: str = "gemini-2.5-pro"

    # RAG
    rag_top_k: int = 5

    # Webhook
    rp_webhook_url: str = ""
    rp_webhook_secret: str = ""  # HMAC-SHA256 signing key; leave blank to skip signing

    @property
    def use_vertex_ai(self) -> bool:
        """Use Vertex AI if a GCP project is configured, otherwise AI Studio."""
        return bool(self.gcp_project)


settings = Settings()
