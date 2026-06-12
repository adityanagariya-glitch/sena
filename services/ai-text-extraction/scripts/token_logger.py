"""
token_logger.py
---------------
Appends a token-usage record to tokens_logs.json in the project root after
every extraction run — whether triggered locally or via the API.

Each entry records:
  timestamp    — UTC ISO-8601 datetime of the run
  source       — "local" (file path) or "s3" (S3 key)
  document     — filename or S3 key
  model_id     — Bedrock model used
  input_tokens — tokens in the request (image + prompt)
  output_tokens— tokens in the model response
  total_tokens — input + output
  latency_ms   — end-to-end Bedrock call latency in milliseconds
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# tokens_logs.json lives in the project root (one level above scripts/)
LOG_FILE = Path(__file__).parent.parent / "tokens_logs.json"


def log_run(
    document: str,
    source: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    latency_ms: int,
) -> None:
    """
    Append one token-usage entry to tokens_logs.json.

    Never raises — failures are logged as warnings so a logging error
    never breaks the extraction result returned to the caller.

    Args:
        document:     Filename or S3 key of the processed document.
        source:       "local" or "s3".
        model_id:     Bedrock model ID string.
        input_tokens: Tokens consumed by the request.
        output_tokens:Tokens in the model's response.
        total_tokens: input_tokens + output_tokens.
        latency_ms:   End-to-end Bedrock call latency in milliseconds.
    """
    entry = {
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "source":       source,
        "document":     document,
        "model_id":     model_id,
        "input_tokens": input_tokens,
        "output_tokens":output_tokens,
        "total_tokens": total_tokens,
        "latency_ms":   latency_ms,
    }

    try:
        if LOG_FILE.exists():
            existing = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        else:
            existing = []

        existing.append(entry)
        LOG_FILE.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.info(
            "Token log — document=%s input=%d output=%d total=%d latency=%dms",
            document, input_tokens, output_tokens, total_tokens, latency_ms,
        )

    except Exception as exc:
        logger.warning("Failed to write token log entry: %s", exc)
