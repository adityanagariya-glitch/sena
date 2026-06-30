import os
from dotenv import load_dotenv

load_dotenv()

# ── AWS ───────────────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", os.environ.get("REGION", "ap-southeast-2"))

# ── Bedrock Knowledge Base ────────────────────────────────────────────────────
KB_ID = os.environ.get("KB_ID", "KFWSFMVU8U")
DS_ID = os.environ.get("DS_ID", "CWJ8UCZSCY")

# ── S3 ────────────────────────────────────────────────────────────────────────
BUCKET_NAME    = os.environ.get("BUCKET_NAME",    "sena-policy-docs")
SOURCE_BUCKET  = os.environ.get("SOURCE_BUCKET",  "")  # Partner storage bucket (optional)
ORG_PREFIX     = os.environ.get("ORG_PREFIX",     "sena/misty/orgs/")
MD_PREFIX      = os.environ.get("MD_PREFIX",      "sena/misty/md/orgs/")

# ── DynamoDB ──────────────────────────────────────────────────────────────────
REGISTRY_TABLE = os.environ.get("REGISTRY_TABLE", "sena-doc-registry")

# ── Auth ──────────────────────────────────────────────────────────────────────
JWT_ENABLED   = os.environ.get("JWT_ENABLED", "false").lower() == "true"
JWT_SECRET    = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"

ADMIN_ROLES = os.environ.get("ADMIN_ROLES", "coordinator,superadmin").split(",")

# ── Ingestion polling ─────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "10"))
POLL_MAX_ATTEMPTS     = int(os.environ.get("POLL_MAX_ATTEMPTS",     "30"))
