import json
import logging
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from app.core.config import settings
from app.models.schemas import ClassificationResult, Message
from app.prompts.classification_prompt import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class BedrockService:
    """
    Handles all communication with AWS Bedrock.
    Uses Claude 3.5 Sonnet via the Bedrock converse API.
    """

    def __init__(self):
        try:
            self.client = boto3.client(
                service_name="bedrock-runtime",
                region_name=settings.AWS_REGION,
            )
            self.model_id = settings.BEDROCK_MODEL_ID
        except NoCredentialsError:
            logger.error(
                "AWS credentials not found. Configure via env vars, ~/.aws/credentials, or IAM role."
            )
            raise

    def classify(
        self,
        current_message: Message,
        history: list[Message],
    ) -> list[ClassificationResult]:
        """
        Sends the conversation to Bedrock and returns parsed classification results.

        Args:
            current_message: The message that triggered the classification call.
            history:         Last N messages for memory context (oldest → newest).

        Returns:
            List of ClassificationResult objects (multi-label).
        """
        user_prompt = build_user_prompt(current_message, history)

        try:
            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={
                    "maxTokens": settings.BEDROCK_MAX_TOKENS,
                    "temperature": settings.BEDROCK_TEMPERATURE,
                },
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            logger.error(f"Bedrock ClientError [{error_code}]: {e}")
            raise RuntimeError(f"Bedrock API error: {error_code}") from e

        raw_text = self._extract_text(response)
        return self._parse_classifications(raw_text)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _extract_text(self, response: dict) -> str:
        """Pulls the raw text content out of a Bedrock converse response."""
        try:
            return response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected Bedrock response structure: {response}")
            raise ValueError("Could not extract text from Bedrock response") from e

    def _parse_classifications(self, raw_text: str) -> list[ClassificationResult]:
        """
        Parses the model's JSON output into ClassificationResult objects.
        Strips markdown fences if the model wraps its response.
        """
        # Strip any accidental markdown code fences
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse model response as JSON: {raw_text}")
            raise ValueError(f"Model returned invalid JSON: {e}") from e

        classifications = data.get("classifications", [])
        if not classifications:
            logger.warning("Model returned empty classifications list.")
            raise ValueError("Model returned no classifications.")

        results = []
        for item in classifications:
            label = item.get("label", "").lower()
            if label not in settings.VALID_LABELS:
                logger.warning(f"Skipping unknown label from model: {label}")
                continue

            results.append(
                ClassificationResult(
                    label=label,
                    confidence=float(item.get("confidence", 0.0)),
                    reason=item.get("reason", "No reason provided."),
                )
            )

        if not results:
            raise ValueError("No valid labels found in model response.")

        return results
