from pydantic_settings import BaseSettings
from typing import Literal

# Load root .env so LANGFUSE_* keys reach os.environ before get_client() runs
try:
    from dotenv import find_dotenv, load_dotenv
    _env = find_dotenv(usecwd=True)
    if _env:
        load_dotenv(_env, override=False)
except ImportError:
    pass


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "Sena Communication Log Classifier"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── AWS Bedrock ───────────────────────────────────────────────────────────
    AWS_REGION: str = "ap-southeast-2"          # Sydney — closest to AUS data residency
    BEDROCK_MODEL_ID: str = "au.anthropic.claude-sonnet-4-5-20250929-v1:0"
    BEDROCK_MAX_TOKENS: int = 1024
    BEDROCK_TEMPERATURE: float = 0.1            # Low temp for consistent classification

    # ── Batch limits ──────────────────────────────────────────────────────────
    # Maximum number of messages accepted per /sentiment-batch call
    # Backend team can raise or lower this via .env — also bump BEDROCK_MAX_TOKENS
    # if raising above 50 (more messages = larger model response)
    BATCH_MAX_MESSAGES: int = 50

    # ── API Security ──────────────────────────────────────────────
    API_KEY: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
