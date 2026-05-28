"""Configuration: env-var loading, AWS clients, Bedrock guardrails, constants."""
import os
import boto3
from pathlib import Path

# Auto-load .env from common locations so users don't have to `export` manually.
try:
    from dotenv import load_dotenv
    _here = Path(__file__).resolve()
    for candidate in (Path.cwd() / ".env", _here.parent / ".env", _here.parents[2] / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            break
except ImportError:
    pass

VERBOSE = os.getenv("SENA_AI_VERBOSE", "").lower() in ("1", "true", "yes")

REGION = "ap-southeast-2"
#MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
MODEL_ID = "au.anthropic.claude-sonnet-4-6"
API_BASE_URL = "https://dev-api.isena.org/api"
KB_MODEL_ID = MODEL_ID

def _parse_guardrails():
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
    # Fallback to single-guardrail env vars
    gid = os.getenv("SENA_AI_BEDROCK_GUARDRAIL_ID", "").strip()
    ver = os.getenv("SENA_AI_BEDROCK_GUARDRAIL_VERSION", "DRAFT").strip()
    return [(gid, ver)] if gid else []


GUARDRAILS = _parse_guardrails()
if GUARDRAILS:
    for i, (gid, ver) in enumerate(GUARDRAILS):
        role = "primary (converse)" if i == 0 else "extra (apply_guardrail)"
else:
    print("[bedrock-guardrails] no guardrails configured — set SENA_AI_BEDROCK_GUARDRAIL_IDS to enable")

BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY", "")  # <-- or hardcode: "ABSK...

if BEDROCK_API_KEY:
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = BEDROCK_API_KEY
    if VERBOSE:
        print("[bedrock] using Bedrock API key (bearer token)")

# ---- AWS clients ----
bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)

_kb_id_raw = os.getenv("SENA_AI_BEDROCK_KB_ID", "").strip()
BEDROCK_KB_IDS = [kb.strip() for kb in _kb_id_raw.split(",") if kb.strip()]
# Backward compat — first KB is the "primary" id; truthy when ANY KB configured.
BEDROCK_KB_ID = BEDROCK_KB_IDS[0] if BEDROCK_KB_IDS else ""

_INFERENCE_PROFILE_PREFIXES = ("global.", "us.", "eu.", "apac.", "us-gov.", "au.")


def _build_kb_model_arn():
    override = os.getenv("SENA_AI_BEDROCK_KB_MODEL_ARN", "").strip()
    if override:
        return override
    # KB uses its own model (Sonnet 4) to avoid legacy model restrictions
    model_for_kb = KB_MODEL_ID
    if model_for_kb.startswith(_INFERENCE_PROFILE_PREFIXES):
        try:
            sts = boto3.client("sts", region_name=REGION)
            account_id = sts.get_caller_identity()["Account"]
            return f"arn:aws:bedrock:{REGION}:{account_id}:inference-profile/{model_for_kb}"
        except Exception as e:
            print(f"[bedrock-kb] STS get_caller_identity failed: {e}")
            print(f"[bedrock-kb] falling back to foundation-model ARN — KB calls may fail")
    return f"arn:aws:bedrock:{REGION}::foundation-model/{model_for_kb}"


BEDROCK_KB_MODEL_ARN = _build_kb_model_arn()
if BEDROCK_KB_IDS:
    print(f"[bedrock-kb] enabled — {len(BEDROCK_KB_IDS)} KB(s): {BEDROCK_KB_IDS}")
else:
    print("[bedrock-kb] disabled — set SENA_AI_BEDROCK_KB_ID to enable RAG")


# ---- AgentCore Memory (24h session) + DynamoDB (30d raw audit, session store) ----
AGENTCORE_MEMORY_ID = os.getenv("SENA_AI_AGENTCORE_MEMORY_ID", "").strip()
AGENTCORE_SESSION_TTL_HOURS = int(os.getenv("SENA_AI_AGENTCORE_SESSION_TTL_HOURS", "24"))
CHAT_AUDIT_TABLE = os.getenv("SENA_AI_CHAT_AUDIT_TABLE", "").strip()
CHAT_AUDIT_TTL_DAYS = int(os.getenv("SENA_AI_CHAT_AUDIT_TTL_DAYS", "30"))

SESSION_TABLE_NAME = os.getenv("SENA_AI_SESSION_TABLE", "").strip()
# Row TTL (DDB native auto-delete) — matches AgentCore raw-event retention.
SESSION_ROW_TTL_DAYS = int(os.getenv("SENA_AI_SESSION_ROW_TTL_DAYS", "90"))

try:
    bedrock_agentcore = boto3.client("bedrock-agentcore", region_name=REGION)
except Exception as e:
    bedrock_agentcore = None
    print(f"[memory] AgentCore client init failed: {e}", file=__import__("sys").stderr)

try:
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    chat_audit_table = dynamodb.Table(CHAT_AUDIT_TABLE) if CHAT_AUDIT_TABLE else None
    session_table = dynamodb.Table(SESSION_TABLE_NAME) if SESSION_TABLE_NAME else None
except Exception as e:
    chat_audit_table = None
    session_table = None
    print(f"[memory] DynamoDB client init failed: {e} — falling back to local session file",
          file=__import__("sys").stderr)

if AGENTCORE_MEMORY_ID and bedrock_agentcore:
    print(f"[memory] AgentCore enabled")
else:
    print("[memory] AgentCore disabled — set SENA_AI_AGENTCORE_MEMORY_ID to enable")

if chat_audit_table:
    print(f"[memory] DDB audit enabled")
else:
    print("[memory] DDB audit disabled — set SENA_AI_CHAT_AUDIT_TABLE to enable")

if session_table:
    print(f"[memory] session table '{SESSION_TABLE_NAME}' enabled (DDB, "
          f"{SESSION_ROW_TTL_DAYS}d row TTL)")
else:
    print("[memory] session table disabled — set SENA_AI_SESSION_TABLE for "
          "multi-process session continuity (falling back to local file)")

# Lookback window used when assembling prompt context from AgentCore short-term events
SESSION_RECENT_TURNS = 6