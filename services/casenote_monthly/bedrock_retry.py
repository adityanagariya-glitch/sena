"""Bedrock retry wrapper with exponential backoff + jitter."""
import logging
import random
import time

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

RETRYABLE_CODES = frozenset({
    "ThrottlingException",
    "InternalServerException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
})


def converse_with_retry(bedrock_runtime, payload: dict, attempts: int = 3, base_delay: float = 1.5) -> dict:
    """Retry wrapper for bedrock_runtime.converse().

    Args:
        bedrock_runtime: boto3 bedrock-runtime client
        payload: converse() arguments (modelId, system, messages, inferenceConfig, etc.)
        attempts: max retry attempts (default 3)
        base_delay: base delay in seconds (default 1.5)

    Returns:
        Bedrock converse() response dict

    Raises:
        Final exception after max attempts exhausted
    """
    for attempt in range(attempts):
        try:
            return bedrock_runtime.converse(**payload)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            if code not in RETRYABLE_CODES or attempt == attempts - 1:
                raise

            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            logger.warning(f"Bedrock {code} (attempt {attempt+1}/{attempts}), retrying in {delay:.1f}s")
            time.sleep(delay)


def sum_usage(usages: list[dict]) -> dict:
    """Sum usage dicts from multiple Bedrock calls.

    totalTokens falls back to input+output when the key is absent, so the
    X-Total-Tokens header can never report 0 while input/output are non-zero.
    """
    return {
        "inputTokens": sum(u.get("inputTokens", 0) for u in usages),
        "outputTokens": sum(u.get("outputTokens", 0) for u in usages),
        "totalTokens": sum(
            u.get("totalTokens") or (u.get("inputTokens", 0) + u.get("outputTokens", 0))
            for u in usages
        ),
    }
