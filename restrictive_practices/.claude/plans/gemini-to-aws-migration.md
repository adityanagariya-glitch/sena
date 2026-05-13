# Migration Plan: Gemini/Vertex AI → AWS Bedrock

## Context

Replace all Google Gemini/Vertex AI calls with AWS Bedrock equivalents:
- **LLMs**: Claude Haiku 4.5 (triage) + Claude Sonnet 4.6 (evaluator + drafter) via Bedrock `converse` API
- **Embeddings**: Cohere Embed English v3 (1024-dim) via Bedrock `invoke_model`

Code flow is unchanged. Every `asyncio.to_thread` wrapper, LangGraph node, RAG retrieval, verdict routing, and API response stays identical. Only the provider client calls inside sync helper functions are swapped.

**Biggest side effect**: embedding dimension drops 3072 → 1024, requiring DB table drop + re-ingest of all NDIS chunks (~400+).

---

## Files to Change (8 files)

### 1. `requirements.txt`

```diff
- google-genai>=1.74.0
+ boto3>=1.34.0
```

---

### 2. `config.py` — full replacement

Remove all GCP/Gemini fields and `use_vertex_ai` property. Add `aws_region`. Keep `triage_model`, `evaluator_model`, `embedding_model` field names so `.env` key names stay compatible.

```python
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

    # AWS Bedrock
    aws_region: str = "ap-southeast-2"        # Sydney — AU data residency (APP 8)

    # Database
    rp_database_url: str = "postgresql+asyncpg://sena_ai:sena_ai@localhost:5433/sena_ai"

    # Embedding model
    embedding_model: str = "cohere.embed-english-v3"

    # Chunking
    chunk_size: int = 1200
    chunk_overlap: int = 120

    # LLM models (Bedrock)
    triage_model: str = "anthropic.claude-haiku-4-5-20251001-v1:0"
    evaluator_model: str = "anthropic.claude-sonnet-4-6-v1:0"

    # RAG
    rag_top_k: int = 5

    # Webhook
    rp_webhook_url: str = ""
    rp_webhook_secret: str = ""


settings = Settings()
```

---

### 3. `pipeline/triage.py`

Remove `google.genai` imports. Add `boto3`. Swap `_make_client()` and `_run_triage()` body. `run_triage()` async wrapper unchanged.

```python
# REMOVE imports:
from google import genai
from google.genai import types

# ADD:
import boto3

# REPLACE _make_client():
def _make_client():
    return boto3.client("bedrock-runtime", region_name=settings.aws_region)

# REPLACE _run_triage() body — same signature, same return type:
def _run_triage(transcript: str) -> TriageResult:
    client = _make_client()
    response = client.converse(
        modelId=settings.triage_model,
        messages=[{"role": "user", "content": [{"text": _TRIAGE_PROMPT.format(transcript=transcript)}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0.0},
    )
    text = response["output"]["message"]["content"][0]["text"]
    if not text:
        raise ValueError("Empty triage response from Bedrock")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Triage response not valid JSON: {exc}. Raw: {text[:200]}") from exc
    parsed = _TriageResponse(**data)
    return TriageResult(flagged=parsed.flagged, action_summary=parsed.action_summary or None)
```

Remove `thinking_config` and `response_mime_type` — not applicable to Bedrock.

---

### 4. `pipeline/evaluator.py`

Same client swap. Remove `response_mime_type`. Prompt already instructs JSON output — keep `json.loads(text)` pattern unchanged.

```python
# REMOVE imports:
from google import genai
from google.genai import types

# ADD:
import boto3

# REPLACE _make_client():
def _make_client():
    return boto3.client("bedrock-runtime", region_name=settings.aws_region)

# REPLACE _run_evaluator() body — keep full signature + return unchanged:
def _run_evaluator(transcript, action_summary, policy_context):
    client = _make_client()
    prompt = _EVALUATOR_PROMPT.format(
        policy_context=policy_context,
        transcript=transcript,
        action_summary=action_summary,
    )
    response = client.converse(
        modelId=settings.evaluator_model,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 8192, "temperature": 0.0},
    )
    text = response["output"]["message"]["content"][0]["text"]
    if not text:
        raise ValueError("Empty evaluator response from Bedrock")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Evaluator response not valid JSON: {exc}. Raw: {text[:200]}") from exc
    parsed = _EvaluatorResponse(**data)
    # ... risk/confidence coercion + return EvaluatorOutput — unchanged
```

`run_evaluator()` async wrapper — **unchanged**.

---

### 5. `pipeline/drafter.py`

Same client swap. Drop `response_schema=_DrafterResponse` (Gemini-specific). Prompt already lists all 18 fields — Sonnet returns valid JSON. Parse with `json.loads` + `_DrafterResponse(**data)`.

```python
# REMOVE imports:
from google import genai
from google.genai import types

# ADD:
import boto3

# REPLACE _make_client():
def _make_client():
    return boto3.client("bedrock-runtime", region_name=settings.aws_region)

# REPLACE _run_drafter() body:
def _run_drafter(transcript: str) -> _DrafterResponse:
    client = _make_client()
    response = client.converse(
        modelId=settings.evaluator_model,
        messages=[{"role": "user", "content": [{"text": _DRAFT_PROMPT.format(transcript=transcript)}]}],
        inferenceConfig={"maxTokens": 4096, "temperature": 0.0},
    )
    text = response["output"]["message"]["content"][0]["text"]
    if not text:
        raise ValueError(
            f"Empty drafter response. finish_reason="
            f"{response.get('stopReason', 'NONE')}"
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Drafter response not valid JSON: {exc}. Raw: {text[:200]}") from exc
    return _DrafterResponse(**data)
```

`run_drafter()` async wrapper — **unchanged**.

---

### 6. `ingestion/embedder.py` — full replacement

Cohere on Bedrock requires `input_type`: `"search_document"` for ingest, `"search_query"` for RAG. Add param to `_embed_sync`. Callers in `rag.py` and scripts are unchanged.

```python
"""Embed document chunks via Bedrock (Cohere) and upsert into pgvector."""

import asyncio
import json as _json
import logging

import boto3
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from ingestion.chunker import DocumentChunk
from models.db import NDISPolicyChunk

logger = logging.getLogger(__name__)


def _make_client():
    return boto3.client("bedrock-runtime", region_name=settings.aws_region)


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = _make_client()
    return _client


def _embed_sync(text: str, input_type: str = "search_document") -> list[float]:
    body = _json.dumps({"texts": [text], "input_type": input_type, "truncate": "END"})
    response = _get_client().invoke_model(
        modelId=settings.embedding_model,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = _json.loads(response["body"].read())
    return result["embeddings"][0]


async def embed_text(text: str) -> list[float]:
    """Async-safe embedding for document ingest."""
    return await asyncio.to_thread(_embed_sync, text, "search_document")


async def embed_query(query: str) -> list[float]:
    """Async-safe embedding for RAG queries."""
    return await asyncio.to_thread(_embed_sync, query, "search_query")


async def upsert_chunks(chunks: list[DocumentChunk], db: AsyncSession) -> int:
    """Embed each chunk and upsert into pgvector. Returns count stored."""
    stored = 0
    for chunk in chunks:
        logger.info("Embedding chunk %s (%d chars)...", chunk.chunk_id, len(chunk.text))
        embedding = await embed_text(chunk.text)

        stmt = (
            insert(NDISPolicyChunk)
            .values(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                category=chunk.category,
                document_source=chunk.document_source,
                risk_level=chunk.risk_level,
                document_type=chunk.document_type,
                embedding=embedding,
            )
            .on_conflict_do_update(
                index_elements=["chunk_id"],
                set_={"text": chunk.text, "document_type": chunk.document_type, "embedding": embedding},
            )
        )
        await db.execute(stmt)
        stored += 1

    await db.commit()
    logger.info("Upserted %d chunks.", stored)
    return stored
```

---

### 7. `models/db.py` — line 28 only

```diff
- embedding: Mapped[list[float]] = mapped_column(HALFVEC(3072), nullable=False)
+ embedding: Mapped[list[float]] = mapped_column(HALFVEC(1024), nullable=False)
```

`db/session.py` — **no change** (`halfvec_cosine_ops` works for any dimension).

---

### 8. `.env`

```diff
- SENA_AI_GCP_PROJECT=
- SENA_AI_GCP_LOCATION=australia-southeast1
- SENA_AI_GEMINI_API_KEY=AIzaSy...
+ SENA_AI_AWS_REGION=ap-southeast-2

- SENA_AI_TRIAGE_MODEL=gemini-3-flash-preview
+ SENA_AI_TRIAGE_MODEL=anthropic.claude-haiku-4-5-20251001-v1:0

- SENA_AI_EVALUATOR_MODEL=gemini-3.1-pro-preview
+ SENA_AI_EVALUATOR_MODEL=anthropic.claude-sonnet-4-6-v1:0

- SENA_AI_EMBEDDING_MODEL=gemini-embedding-2
+ SENA_AI_EMBEDDING_MODEL=cohere.embed-english-v3
```

AWS credentials: boto3 reads `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` from env, or IAM role automatically. No code change needed.

---

## DB Migration (run after code changes)

`rp_ndis_policy_chunks` must be dropped — column type changes dimension (3072 → 1024).
`behaviour_support_plans` and `rp_case_note_runs` are unaffected.

```bash
# 1. Drop old chunks table
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai \
  -c "DROP TABLE IF EXISTS rp_ndis_policy_chunks CASCADE;"

# 2. Start server — create_tables() recreates with HALFVEC(1024)
uvicorn main:app --reload --port 8084

# 3. Re-ingest all NDIS policy docs
python scripts/ingest_ndis_policies.py

# 4. Verify chunk count
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai \
  -c "SELECT COUNT(*) FROM rp_ndis_policy_chunks;"
```

---

## Files NOT changing

`pipeline/rag.py`, `pipeline/cross_check.py`, `pipeline/graph.py`, `api/routes.py`,
`models/schemas.py`, `ingestion/chunker.py`, `db/session.py`, `pipeline/webhook.py`

---

## AU Data Residency

`ap-southeast-2` (Sydney) required for APP 8 compliance. Verify Claude Haiku 4.5 and Sonnet 4.6 are available in that region before deploying. Fallback: cross-region inference profile `us.anthropic.claude-...` — but breaks AU residency, needs compliance sign-off.

---

## Verification

```bash
# Install new dep
pip install "boto3>=1.34.0"

# Confirm Bedrock access
python -c "import boto3; c=boto3.client('bedrock-runtime',region_name='ap-southeast-2'); print('ok')"

# Smoke tests (no server needed)
python scripts/test_triage.py
python scripts/test_evaluator.py
python scripts/test_draft_endpoint.py

# Full pipeline regression
python scripts/test_sarah_note.py    # physical + chemical + seclusion fixture
python scripts/test_form_api.py      # 8 real-data scenarios, all 4 verdict outcomes

# Audit rows
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai \
  -c "SELECT case_note_id, triage_flagged, authorisation_status, alert_required FROM rp_case_note_runs ORDER BY created_at DESC LIMIT 5;"
```
