import asyncio
import json
import logging
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status
from langfuse import observe, get_client

from config import get_settings
from prompts import build_messages, get_system_prompt

logger = logging.getLogger(__name__)

langfuse = get_client()
_SERVICE = "shift-summary"

_lf_prompt = None
try:
    _lf_prompt = langfuse.get_prompt(f"{_SERVICE}/consolidate-system")
except Exception:
    pass


@lru_cache
def _get_bedrock_client():
    """
    Cached boto3 Bedrock runtime client.

    Credentials are intentionally NOT passed here — boto3 resolves them from the
    default credential chain (the EC2 instance's IAM role / instance profile on
    the server). Only the region is supplied.
    """
    settings = get_settings()
    return boto3.client(
        service_name="bedrock-runtime",
        region_name=settings.aws_region,
    )


def _build_request_body(summaries: list[str]) -> dict:
    """
    Build the Bedrock request body for Claude models (Messages API format).
    All model parameters are driven by config — nothing is hardcoded.
    The prompt is owned entirely by prompts.py.
    Includes prompt caching on system prompt for cost optimization.
    """
    settings = get_settings()
    system_prompt = get_system_prompt()
    return {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": settings.bedrock_max_tokens,
        "temperature": settings.bedrock_temperature,
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ],
        "messages": build_messages(summaries),
    }


@observe(as_type="generation", name="shift-summary-consolidate", capture_input=False, capture_output=False)
async def consolidate_summaries(summaries: list[str]) -> tuple[str, dict]:
    """
    Call AWS Bedrock with Claude to consolidate the provided summaries.
    Returns a tuple of (consolidated text, usage dict with input/output token counts).
    Raises HTTPException on Bedrock or parsing errors.
    """
    settings = get_settings()
    client = _get_bedrock_client()
    body = _build_request_body(summaries)

    logger.info(
        "Invoking Bedrock model '%s' with %d summaries.",
        settings.bedrock_model_id,
        len(summaries),
    )

    try:
        response = await asyncio.to_thread(
            client.invoke_model,
            modelId=settings.bedrock_model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        error_msg = exc.response["Error"]["Message"]
        logger.error("Bedrock ClientError [%s]: %s", error_code, error_msg)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Bedrock invocation failed [{error_code}]: {error_msg}",
        ) from exc
    except BotoCoreError as exc:
        logger.error("Bedrock BotoCoreError: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Bedrock connection error: {str(exc)}",
        ) from exc

    try:
        response_body = json.loads(response["body"].read())
        consolidated = response_body["content"][0]["text"].strip()
        raw_usage = response_body.get("usage", {})
        # Include cache tokens in input calculation
        input_total = raw_usage.get("input_tokens", 0) + raw_usage.get("cache_read_input_tokens", 0) + raw_usage.get("cache_creation_input_tokens", 0)
        output_total = raw_usage.get("output_tokens", 0)
        usage = {
            "input_tokens": input_total,
            "output_tokens": output_total,
            "total_tokens": input_total + output_total,
        }
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.error("Failed to parse Bedrock response: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected Bedrock response format: {str(exc)}",
        ) from exc

    langfuse.update_current_generation(
        model=settings.bedrock_model_id,
        input="\n\n".join(summaries)[:2000],
        output=consolidated[:2000],
        usage_details={
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
            "total": usage.get("total_tokens", 0),
        },
        prompt=_lf_prompt,
        metadata={"service": _SERVICE},
    )
    logger.info("Successfully consolidated %d summaries.", len(summaries))
    return consolidated, usage