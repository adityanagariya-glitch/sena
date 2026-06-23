# config.py
import os
import logging

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)

# ── AWS Region ────────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", os.environ.get("REGION", "ap-southeast-2"))

# ── Bedrock Knowledge Base ────────────────────────────────────────────────────
KB_ID = os.environ.get("KB_ID", "KFWSFMVU8U")
DS_ID = os.environ.get("DS_ID", "CWJ8UCZSCY")

# ── Guardrails ────────────────────────────────────────────────────────────────
GUARDRAIL_ID      = os.environ.get("GUARDRAIL_ID", "j9x9dysm5m3h")
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "DRAFT")

# ── Models ───────────────────────────────────────────────────────────────────
CLASSIFIER_MODEL  = os.environ.get("CLASSIFIER_MODEL",  "apac.amazon.nova-micro-v1:0")
RERANKER_MODEL    = os.environ.get("RERANKER_MODEL",     "apac.amazon.nova-micro-v1:0")
REWRITER_MODEL    = os.environ.get("REWRITER_MODEL",     "apac.amazon.nova-lite-v1:0")
GENERATION_MODEL  = os.environ.get("GENERATION_MODEL",  "au.anthropic.claude-haiku-4-5-20251001-v1:0")
JUDGE_MODEL       = os.environ.get("JUDGE_MODEL",       "au.anthropic.claude-sonnet-4-6")
EMBED_MODEL       = os.environ.get("EMBED_MODEL",       "amazon.titan-embed-text-v2:0")

# Bedrock native reranker - manual cross-region call
RERANK_REGION = os.environ.get("RERANK_REGION", "ap-northeast-1")
AMAZON_RERANK_MODEL_ID = os.environ.get(
    "AMAZON_RERANK_MODEL_ID",
    "amazon.rerank-v1:0"
)
AMAZON_RERANK_MODEL_ARN = os.environ.get(
    "AMAZON_RERANK_MODEL_ARN",
    f"arn:aws:bedrock:{RERANK_REGION}::foundation-model/{AMAZON_RERANK_MODEL_ID}"
)

# ── Retrieval ─────────────────────────────────────────────────────────────────
NUM_RESULTS       = int(os.environ.get("NUM_RESULTS",  "20"))
RERANK_TOP        = int(os.environ.get("RERANK_TOP",   "8"))
RERANK_PROVIDER   = os.environ.get("RERANK_PROVIDER", "amazon")
RERANK_COMPARE    = os.environ.get("RERANK_COMPARE", "false").lower() == "true"
RERANK_LOG_PATH   = os.environ.get("RERANK_LOG_PATH", "logs/rerank_comparison.jsonl")

# ── S3 ────────────────────────────────────────────────────────────────────────
BUCKET_NAME       = os.environ.get("BUCKET_NAME",  "sena-policy-docs")
BUCKET_PREFIX     = os.environ.get("BUCKET_PREFIX", "sena/misty/")
ORG_PREFIX        = os.environ.get("ORG_PREFIX", "sena/misty/orgs/")
MD_PREFIX         = os.environ.get("MD_PREFIX",  "sena/misty/md/orgs/")
REGISTRY_TABLE    = os.environ.get("REGISTRY_TABLE", "sena-doc-registry")

# ── Messages ──────────────────────────────────────────────────────────────────
MESSAGES = {
    "OFF_TOPIC": "I can only help with NDIS and organisation policy questions.",
    "HARMFUL":   "I'm not able to help with that.",
    "SENSITIVE": (
        "It looks like your message contains personal details. "
        "Please rephrase your question without names, addresses, or ID numbers "
        "and I'll do my best to help."
    ),
    "NOT_IN_KB": "Sorry, I don't have that information in the policy documents. Please ask a different question or provide more context.",
    "BLOCKED":    "Sorry, I'm not able to assist with that request.",
    "ERROR":      "Sorry, something went wrong while processing your request. Please try again later.",
    "GREETING":  "Hello! I'm here to help with NDIS and organisation policy questions. What would you like to know?",
    "FALLBACK":  "I'm not sure how to help with that. Try rephrasing your question.",
}

# ── Memory ──────────────────────────────────────────────────────────────
MEMORY_ID = os.environ.get("MEMORY_ID", "senaPolicyProceduresMemory-FGIxWL6gih") # Memory ID: senaPolicyProceduresMemory-FGIxWL6gih

# ── Environment & DynamoDB ────────────────────────────────────────────────
ENV            = os.environ.get("ENV", "dev")
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", f"sena-{ENV}-chat-sessions")
TURNS_TABLE    = os.environ.get("TURNS_TABLE",    f"sena-{ENV}-chat-turns")

# # ── Auto Update and Auto Deletion ──────────────────────────────────────────────────────────────
ADMIN_ROLES = os.environ.get("ADMIN_ROLES", "coordinator,superadmin").split(",")
ORG_ADMIN   = os.environ.get("ORG_ADMIN", "superadmin,admin,coordinator").split(",")


BACKEND_API_BASE = os.environ.get("BACKEND_API_BASE", "")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "")

# ── Langfuse ──────────────────────────────────────────────────────────────────
# load_dotenv() here ensures env vars are available when config is imported
# directly (e.g., python scripts/pipeline.py REPL). FastAPI main.py also calls
# load_dotenv() early — calling it twice is safe (idempotent).
from dotenv import load_dotenv
load_dotenv()

from langfuse import get_client

langfuse = get_client()  # auto-disabled if LANGFUSE_PUBLIC_KEY / SECRET_KEY not set