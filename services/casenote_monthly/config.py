"""Configuration: env-var loading, AWS Bedrock client, guardrails, constants.

Trimmed copy of services/staff/config.py — keeps only what the monthly
case-note summary service needs (Bedrock + backend API base URL). The
AgentCore/DynamoDB/session machinery from the staff service is intentionally
dropped: this service is stateless.
"""
import os
import boto3
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path("/home/main/SENA/.env"), override=False)
except ImportError:
    pass

VERBOSE = os.getenv("SENA_AI_VERBOSE", "").lower() in ("1", "true", "yes")

REGION = "ap-southeast-2"
MODEL_ID = "au.anthropic.claude-sonnet-4-6"
API_BASE_URL = "https://dev-api.isena.org/api"


def _parse_guardrails():
    """Parse SENA_AI_BEDROCK_GUARDRAIL_IDS ("id:ver,id2:ver2") with single-var fallback."""
    raw = os.getenv("SENA_AI_BEDROCK_GUARDRAIL_IDS", "").strip()
    if raw:
        out = []
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                gid, ver = entry.split(":", 1)
            else:
                gid, ver = entry, "DRAFT"
            out.append((gid.strip(), ver.strip()))
        return out
    gid = os.getenv("SENA_AI_BEDROCK_GUARDRAIL_ID", "").strip()
    ver = os.getenv("SENA_AI_BEDROCK_GUARDRAIL_VERSION", "DRAFT").strip()
    return [(gid, ver)] if gid else []


GUARDRAILS = _parse_guardrails()
if not GUARDRAILS:
    print("[bedrock-guardrails] no guardrails configured — set SENA_AI_BEDROCK_GUARDRAIL_IDS to enable")

BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY", "")
if BEDROCK_API_KEY:
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = BEDROCK_API_KEY
    if VERBOSE:
        print("[bedrock] using Bedrock API key (bearer token)")

# ---- AWS clients ----
bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)
