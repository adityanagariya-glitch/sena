from __future__ import annotations

from pydantic import Field
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
    # SENA_AI_CASE_NOTE_FETCH_LIMIT — hard cap on past notes pulled per /context call
    case_note_fetch_limit: int = 10

    # ── External: SENA org backend (real case-note source) ────────────────────
    # Two-step fetch:
    #   1. GET {base}/organization/case-note/get-all?clientId&memberId&limit&status=completed
    #   2. GET {base}/organization/case-note/{caseNoteId}  (per note, for full content)
    # SENA_AI_CASE_NOTE_API_BASE_URL — org backend base, no trailing slash
    case_note_api_base_url: str = "http://localhost:8085"
    # SENA_AI_CASE_NOTE_API_TOKEN — bearer token for the org backend (blank in dev)
    case_note_api_token: str = ""
    # SENA_AI_CASE_NOTE_USE_STUB — True → fixtures; False → call the org backend
    case_note_use_stub: bool = True

    # ── Gemini ────────────────────────────────────────────────────────────────
    # SENA_AI_GEMINI_API_KEY
    gemini_api_key: str = ""
    # SENA_AI_GEMINI_MODEL_ID — standard generate_content model (NOT Live API)
    # gemini-3.1-flash-live-preview is Live API only (WebSocket) and cannot be used here.
    gemini_model_id: str = "gemini-3.5-flash"
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

    # ── AWS Bedrock (transcript drafter — run_draft offloads to thread pool) ────
    # SENA_AI_AWS_REGION — Sydney for AU data residency
    aws_region: str = "ap-southeast-2"
    # Leave blank to use IAM instance role on EC2 (recommended for prod)
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    # SENA_AI_BEDROCK_MODEL_ID
    bedrock_model_id: str = "au.anthropic.claude-sonnet-4-6"

    # ── Auth ──────────────────────────────────────────────────────────────────
    # SENA_AI_AUTH_MODE: "dev_header" | "jwt"
    auth_mode: str = "dev_header"

    # ── Pipeline LLM models (LangGraph 5-step triage → RAG → eval → BSP → verdict) ──
    # SENA_AI_TRIAGE_MODEL — Haiku: cheap YES/NO gate (Bedrock converse, maxTokens=512)
    triage_model: str = "au.anthropic.claude-haiku-4-5-20251001-v1:0"
    # SENA_AI_EVALUATOR_MODEL — Sonnet: structured verdict + drafter (maxTokens=8192)
    evaluator_model: str = "au.anthropic.claude-sonnet-4-6"
    # SENA_AI_CLASSIFIER_MODEL — Haiku: field extraction from raw paragraph
    classifier_model: str = "au.anthropic.claude-haiku-4-5-20251001-v1:0"
    # SENA_AI_SUMMARIZER_MODEL — Haiku: rolling context summary across case notes
    summarizer_model: str = "au.anthropic.claude-haiku-4-5-20251001-v1:0"

    # ── RAG / Embeddings (pgvector HNSW, Cohere Embed English v3, 1024-dim) ──
    # SENA_AI_EMBEDDING_MODEL — must match at ingest AND query time; re-ingest if changed
    embedding_model: str = "cohere.embed-english-v3"
    chunk_size: int = 1200
    chunk_overlap: int = 120
    rag_top_k: int = 5  # legacy fallback — prefer rag_top_k_fetch + rag_max_chunks
    # Smarter RAG: fetch more, score-filter, keep best
    # SENA_AI_RAG_TOP_K_FETCH — fetch this many from pgvector (wider net)
    rag_top_k_fetch: int = 10
    # SENA_AI_RAG_MAX_CHUNKS — keep at most this many after distance filtering
    rag_max_chunks: int = 3
    # SENA_AI_RAG_SIMILARITY_THRESHOLD — cosine distance cut-off (lower = stricter)
    # pgvector <=> returns cosine distance (0=identical, 2=opposite); 0.35 ≈ similarity 0.65
    rag_similarity_threshold: float = 0.35

    # ── Tiered routing ─────────────────────────────────────────────────────────
    # SENA_AI_TRIAGE_CONFIDENCE_THRESHOLD — triage_confidence >= this → Haiku evaluator
    # (fast, cheap, action_summary-only); below → Sonnet evaluator (full transcript)
    triage_confidence_threshold: float = 0.85

    # ── S3 / Amazon Transcribe (audio drafting — POST /draft/audio) ───────────
    # Read WITHOUT SENA_AI_ prefix — standard boto3/AWS env vars, override per role
    s3_region: str = Field(default="", validation_alias="S3_REGION")
    s3_access_key_id: str = Field(default="", validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(default="", validation_alias="S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field(default="", validation_alias="S3_BUCKET")
    s3_public_base_url: str = Field(default="", validation_alias="S3_PUBLIC_BASE_URL")
    # SENA_AI_TRANSCRIPTION_BUCKET — required for POST /draft/audio; returns 503 if blank
    transcription_bucket: str = ""
    transcription_language: str = "en-AU"
    transcription_vocab_name: str = ""

    # ── Restrictive practices alert webhook ───────────────────────────────────
    # SENA_AI_RP_WEBHOOK_URL / SECRET — fires only on UNAUTHORISED verdict (alert_required=True)
    rp_webhook_url: str = ""
    rp_webhook_secret: str = ""

    # ── Restrictive practices API basic auth (optional — leave blank for local dev) ──
    # SENA_AI_BASIC_AUTH_USER / SENA_AI_BASIC_AUTH_PASSWORD
    basic_auth_user: str = ""
    basic_auth_password: str = ""

    # ── Voice resumption ──────────────────────────────────────────────────────
    # SENA_AI_RESUMPTION_HANDLE_TTL_SEC
    resumption_handle_ttl_sec: int = 600


settings = CaseReviewSettings()
