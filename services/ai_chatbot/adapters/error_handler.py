"""Error handler: explain Bedrock errors using Claude.

Catches service adapter errors and generates user-friendly explanations.
"""
import logging
from typing import Dict, Any
import boto3

logger = logging.getLogger(__name__)


async def explain_error(
    error: Exception,
    context: Dict[str, Any],
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0",
) -> str:
    """Generate user-friendly explanation for an error using Claude.

    Args:
        error: Exception that occurred
        context: Request context (question, user_id, etc.)
        bedrock_model_id: Claude model to use

    Returns:
        User-friendly error message
    """
    error_text = str(error)
    question = context.get("question", "unknown question")
    user_id = context.get("user_id", "unknown user")

    prompt = f"""
The following error occurred while processing a user question:

Error: {error_text}
Question: {question}

Generate a brief, friendly explanation of what went wrong and what the user should try next.
Keep it to 1-2 sentences.
"""

    try:
        client = boto3.client("bedrock-runtime")
        resp = client.invoke_model(
            modelId=bedrock_model_id,
            contentType="application/json",
            body={
                "prompt": prompt,
                "max_tokens": 100,
                "temperature": 0,
            },
        )
        result = resp["body"].read().decode("utf-8")
        # Parse response (depends on model format)
        if isinstance(result, str):
            return result.strip()
        return "An error occurred. Please try again."
    except Exception as e:
        logger.warning(f"Failed to explain error with Bedrock: {e}")
        return (
            f"Sorry, I encountered an error: {error_text[:100]}. "
            "Please try rephrasing your question."
        )


async def handle_adapter_error(
    error: Exception,
    service_name: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Convert adapter error to user-facing event.

    Args:
        error: Exception from adapter
        service_name: Name of service that failed (staff, policy)
        context: Request context

    Returns:
        Event dict (type: error, text: explanation)
    """
    logger.exception(f"Adapter error from {service_name}: {error}")

    explanation = await explain_error(error, context)

    return {
        "type": "error",
        "text": explanation,
        "service": service_name,
        "error_class": type(error).__name__,
    }
