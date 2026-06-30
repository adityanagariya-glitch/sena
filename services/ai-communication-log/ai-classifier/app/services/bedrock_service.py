import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from langfuse import observe, get_client

from app.core.config import settings
from app.models.schemas import (
    BreakdownAssessment,
    RiskAssessment,
    SentimentResult,
    TokenUsage,
    Message,
)
from app.prompts.sentiment_batch_prompt import BATCH_SYSTEM_PROMPT, build_batch_user_prompt

logger = logging.getLogger(__name__)

langfuse = get_client()
_SERVICE = "ai-communication-log"

# Fetch prompt from Langfuse Prompt Management; fall back to hardcoded string
_lf_prompt = None
try:
    _lf_prompt = langfuse.get_prompt(f"{_SERVICE}/sentiment-batch-system")
    BATCH_SYSTEM_PROMPT = _lf_prompt.compile()
except Exception:
    pass  # _lf_prompt stays None; hardcoded BATCH_SYSTEM_PROMPT is used

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
class MessageAnalysisItem:
    """Full analysis for a single message — internal dataclass, mirrors MessageAnalysis schema."""
    sentiment: SentimentResult
    risk: RiskAssessment
    breakdown: BreakdownAssessment
    outcome: str
    recommended_action: Optional[str]


@dataclass
class BatchOutput:
    """Parsed batch model response — passed from BedrockService to SentimentBatchService."""
    message_analyses: list[MessageAnalysisItem]   # ordered 0..N-1, one per input message
    token_usage: Optional[TokenUsage] = None


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

    # ── Private helpers ────────────────────────────────────────────────────────

    def _extract_text(self, response: dict) -> str:
        try:
            return response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected Bedrock response structure: {response}")
            raise ValueError("Could not extract text from Bedrock response") from e

    def _parse_sentiment_from_key(self, data: dict, key: str) -> SentimentResult:
        raw = data.get(key, {})
        label = raw.get("label", "neutral").lower()
        if label not in _VALID_SENTIMENT_LABELS:
            logger.warning(f"Unknown sentiment label '{label}' in '{key}', defaulting to 'neutral'.")
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

    # ── Batch analysis ─────────────────────────────────────────────────────────

    @observe(as_type="generation", name="sentiment-classify", capture_input=False, capture_output=False)
    def analyse_batch(self, messages: list[Message]) -> BatchOutput:
        """
        Sends a conversation window (up to BATCH_MAX_MESSAGES messages) to Bedrock
        and returns a full analysis (sentiment, risk, breakdown, outcome, recommended_action)
        for every individual message in the batch.
        """
        user_prompt = build_batch_user_prompt(messages)

        try:
            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": BATCH_SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={
                    "maxTokens": settings.BEDROCK_MAX_TOKENS,
                    "temperature": settings.BEDROCK_TEMPERATURE,
                },
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            logger.error(f"Bedrock ClientError (batch) [{error_code}]: {e}")
            raise RuntimeError(f"Bedrock API error: {error_code}") from e

        raw_text = self._extract_text(response)
        usage_raw = response.get("usage", {})
        token_usage = TokenUsage(
            input_tokens=usage_raw.get("inputTokens", 0),
            output_tokens=usage_raw.get("outputTokens", 0),
            total_tokens=usage_raw.get("totalTokens", 0),
        )
        langfuse.update_current_generation(
            model=self.model_id,
            input=user_prompt,
            output=raw_text,
            usage_details={
                "input": usage_raw.get("inputTokens", 0),
                "output": usage_raw.get("outputTokens", 0),
            },
            prompt=_lf_prompt,
            metadata={"service": _SERVICE},
        )
        batch_output = self._parse_batch_response(raw_text)
        batch_output.token_usage = token_usage
        return batch_output

    def _parse_batch_response(self, raw_text: str) -> BatchOutput:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse batch model response as JSON: {raw_text}")
            raise ValueError(f"Model returned invalid JSON: {e}") from e

        return BatchOutput(message_analyses=self._parse_message_analyses(data))

    def _parse_message_analyses(self, data: dict) -> list[MessageAnalysisItem]:
        raw = data.get("messages", [])
        if not isinstance(raw, list):
            logger.warning("'messages' field in batch response is not a list — returning empty.")
            return []

        # Sort by index so order matches the original input message list
        raw_sorted = sorted(raw, key=lambda x: x.get("index", 0))

        results = []
        for item in raw_sorted:
            results.append(MessageAnalysisItem(
                sentiment=self._parse_sentiment_from_key(item, "sentiment"),
                risk=self._parse_risk(item),
                breakdown=self._parse_breakdown(item),
                outcome=self._parse_outcome(item),
                recommended_action=self._parse_recommended_action(item),
            ))
        return results
