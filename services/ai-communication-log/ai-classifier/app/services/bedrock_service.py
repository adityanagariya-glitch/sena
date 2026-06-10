import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from app.core.config import settings
from app.models.schemas import (
    BreakdownAssessment,
    ClassificationResult,
    RiskAssessment,
    SentimentResult,
    Message,
)
from app.prompts.classification_prompt import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

_VALID_SENTIMENT_LABELS = {
    "positive_satisfied",
    "neutral",
    "frustrated_dissatisfied",
    "distressed_upset",
    "confused_uncertain",
    "engaged",
    "disengaged",
}

_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}
_VALID_OUTCOMES = {"resolved", "unresolved", "pending"}


@dataclass
class BedrockOutput:
    """Parsed model response — passed from BedrockService to ClassificationService."""
    classifications: list[ClassificationResult]
    sentiment: SentimentResult
    risk: RiskAssessment
    breakdown: BreakdownAssessment
    outcome: str
    recommended_action: Optional[str]


class BedrockService:
    """Handles all communication with AWS Bedrock (Claude via converse API)."""

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
    ) -> BedrockOutput:
        """
        Sends the conversation to Bedrock and returns a fully parsed BedrockOutput
        covering classifications, sentiment, risk, breakdown, outcome, and recommended_action.
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
        return self._parse_response(raw_text)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _extract_text(self, response: dict) -> str:
        try:
            return response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected Bedrock response structure: {response}")
            raise ValueError("Could not extract text from Bedrock response") from e

    def _parse_response(self, raw_text: str) -> BedrockOutput:
        """Parses the full model JSON into a BedrockOutput. Applies safe fallbacks per section."""
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

        return BedrockOutput(
            classifications=self._parse_classifications(data),
            sentiment=self._parse_sentiment(data),
            risk=self._parse_risk(data),
            breakdown=self._parse_breakdown(data),
            outcome=self._parse_outcome(data),
            recommended_action=self._parse_recommended_action(data),
        )

    def _parse_classifications(self, data: dict) -> list[ClassificationResult]:
        raw = data.get("classifications", [])
        if not raw:
            logger.warning("Model returned empty classifications list.")
            raise ValueError("Model returned no classifications.")

        results = []
        for item in raw:
            label = item.get("label", "").lower()
            if label not in settings.VALID_LABELS:
                logger.warning(f"Skipping unknown classification label: {label}")
                continue
            results.append(
                ClassificationResult(
                    label=label,
                    confidence=float(item.get("confidence", 0.0)),
                    reason=item.get("reason", "No reason provided."),
                )
            )

        if not results:
            raise ValueError("No valid classification labels found in model response.")
        return results

    def _parse_sentiment(self, data: dict) -> SentimentResult:
        raw = data.get("sentiment", {})
        label = raw.get("label", "neutral").lower()
        if label not in _VALID_SENTIMENT_LABELS:
            logger.warning(f"Unknown sentiment label '{label}', defaulting to 'neutral'.")
            label = "neutral"
        return SentimentResult(
            label=label,
            confidence=float(raw.get("confidence", 0.0)),
            reason=raw.get("reason", "No sentiment reason provided."),
        )

    def _parse_risk(self, data: dict) -> RiskAssessment:
        raw = data.get("risk", {})
        level = raw.get("level", "low").lower()
        if level not in _VALID_RISK_LEVELS:
            logger.warning(f"Unknown risk level '{level}', defaulting to 'low'.")
            level = "low"
        indicators = raw.get("indicators", [])
        if not isinstance(indicators, list):
            indicators = []
        return RiskAssessment(
            level=level,
            indicators=[str(i) for i in indicators],
            reason=raw.get("reason", "No risk reason provided."),
        )

    def _parse_breakdown(self, data: dict) -> BreakdownAssessment:
        raw = data.get("breakdown", {})
        detected = bool(raw.get("detected", False))
        reasons = raw.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = []
        return BreakdownAssessment(
            detected=detected,
            reasons=[str(r) for r in reasons] if detected else [],
        )

    def _parse_outcome(self, data: dict) -> str:
        outcome = str(data.get("outcome", "pending")).lower()
        if outcome not in _VALID_OUTCOMES:
            logger.warning(f"Unknown outcome '{outcome}', defaulting to 'pending'.")
            outcome = "pending"
        return outcome

    def _parse_recommended_action(self, data: dict) -> Optional[str]:
        action = data.get("recommended_action")
        if not action or str(action).lower() in ("null", "none", ""):
            return None
        return str(action)
