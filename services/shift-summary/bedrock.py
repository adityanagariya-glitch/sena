import asyncio
import json
import logging
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from config import get_settings
from prompts import build_messages, get_system_prompt

logger = logging.getLogger(__name__)


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
    """
    settings = get_settings()
    return {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": settings.bedrock_max_tokens,
        "temperature": settings.bedrock_temperature,
        "system": get_system_prompt(),
        "messages": build_messages(summaries),
    }


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
        usage = response_body.get("usage", {})
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.error("Failed to parse Bedrock response: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected Bedrock response format: {str(exc)}",
        ) from exc

    logger.info("Successfully consolidated %d summaries.", len(summaries))
    return consolidated, usage