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

# ── Models ────────────────────────────────────────────────────────────────────
CLASSIFIER_MODEL  = os.environ.get("CLASSIFIER_MODEL",  "amazon.nova-micro-v1:0")
RERANKER_MODEL    = os.environ.get("RERANKER_MODEL",     "amazon.nova-micro-v1:0")
REWRITER_MODEL    = os.environ.get("REWRITER_MODEL",     "amazon.nova-lite-v1:0")
GENERATION_MODEL  = os.environ.get("GENERATION_MODEL",  "au.anthropic.claude-haiku-4-5-20251001-v1:0")
JUDGE_MODEL       = os.environ.get("JUDGE_MODEL",       "au.anthropic.claude-sonnet-4-6")
EMBED_MODEL       = os.environ.get("EMBED_MODEL",       "amazon.titan-embed-text-v2:0")

# ── Retrieval ─────────────────────────────────────────────────────────────────
NUM_RESULTS       = int(os.environ.get("NUM_RESULTS",  "10"))
RERANK_TOP        = int(os.environ.get("RERANK_TOP",   "5"))

# ── S3 ────────────────────────────────────────────────────────────────────────
BUCKET_NAME       = os.environ.get("BUCKET_NAME",  "sena-policy-docs")
BUCKET_PREFIX     = os.environ.get("BUCKET_PREFIX", "sena/misty/")
ORG_PREFIX        = os.environ.get("ORG_PREFIX", "sena/misty/orgs/")
REGISTRY_TABLE    = os.environ.get("REGISTRY_TABLE", "sena-doc-registry")

# ── Messages ──────────────────────────────────────────────────────────────────
MESSAGES = {
    "OFF_TOPIC":  "I'm only able to assist with NDIS and organisation policy related questions.",
    "HARMFUL":    "I'm not able to help with that.",
    "SENSITIVE":  "That question contains sensitive information. Could you rephrase without personal details?",
    "NOT_IN_KB":  "I don't have the authority to answer that based on the information available to me.",
    "ERROR":      "Something went wrong. Please try again.",
    "BLOCKED":    "I'm not able to respond to that."
}

# ── Memory ──────────────────────────────────────────────────────────────
MEMORY_ID = os.environ.get("MEMORY_ID", "senaPolicyProceduresMemory-FGIxWL6gih") # Memory ID: senaPolicyProceduresMemory-FGIxWL6gih

# ── Environment & DynamoDB ────────────────────────────────────────────────
ENV            = os.environ.get("ENV", "dev")
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", f"sena-{ENV}-chat-sessions")
TURNS_TABLE    = os.environ.get("TURNS_TABLE",    f"sena-{ENV}-chat-turns")
