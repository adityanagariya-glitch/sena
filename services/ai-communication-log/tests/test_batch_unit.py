"""
Sena Communication Log — Batch Sentiment Unit Tests
No network calls. All Bedrock responses are mocked.

Run:
    pytest tests/test_batch_unit.py -v
    pytest tests/test_batch_unit.py -v -k "parsing"
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.services.bedrock_service import BedrockService, BatchOutput, MessageAnalysisItem
from app.services.sentiment_batch_service import SentimentBatchService
from app.models.schemas import (
    Message,
    SentimentBatchRequest,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _bedrock_response(model_json: dict) -> dict:
    return {
        "output": {
            "message": {
                "content": [{"text": json.dumps(model_json)}]
            }
        }
    }


def _make_message(role="support_worker", text="Hello.", ts="2025-06-01T10:00:00Z") -> Message:
    return Message(role=role, text=text, timestamp=datetime.fromisoformat(ts.replace("Z", "+00:00")))


def _make_batch_request(messages=None) -> SentimentBatchRequest:
    if messages is None:
        messages = [
            _make_message("client", "I need help.", "2025-06-01T10:00:00Z"),
            _make_message("support_worker", "Wait a moment.", "2025-06-01T10:01:00Z"),
            _make_message("client", "Please, it hurts.", "2025-06-01T10:02:00Z"),
        ]
    return SentimentBatchRequest(
        conversation_id="test_batch_conv",
        provider_id="test_org",
        messages=messages,
    )


def _msg_analysis(
    index,
    sentiment_label="neutral",
    sentiment_confidence=0.80,
    sentiment_reason="Standard tone.",
    risk_level="low",
    risk_indicators=None,
    risk_reason="No concern.",
    breakdown_detected=False,
    breakdown_reasons=None,
    outcome="pending",
    recommended_action=None,
):
    return {
        "index": index,
        "sentiment": {
            "label": sentiment_label,
            "confidence": sentiment_confidence,
            "reason": sentiment_reason,
        },
        "risk": {
            "level": risk_level,
            "indicators": risk_indicators or [],
            "reason": risk_reason,
        },
        "breakdown": {
            "detected": breakdown_detected,
            "reasons": breakdown_reasons or [],
        },
        "outcome": outcome,
        "recommended_action": recommended_action,
    }


# 3-message batch payload returned by the model
BATCH_PAYLOAD = {
    "messages": [
        _msg_analysis(0, "engaged", 0.82, "Client actively sought help.", "low", [], "No risk."),
        _msg_analysis(1, "disengaged", 0.88, "Worker gave minimal response.", "medium",
                      ["client request dismissed"], "Worker dismissed client request."),
        _msg_analysis(2, "distressed_upset", 0.95, "Client expressed pain.", "high",
                      ["client in pain", "worker unresponsive"], "Client at risk.",
                      breakdown_detected=True, breakdown_reasons=["client request ignored"],
                      outcome="unresolved", recommended_action="Escalate to coordinator."),
    ]
}


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    with patch("app.services.bedrock_service.boto3") as mock_boto3:
        mock_boto3.client.return_value = MagicMock()
        service = BedrockService()
        yield service


@pytest.fixture
def mock_batch_converse(svc):
    def _set(model_json: dict):
        svc.client.converse.return_value = _bedrock_response(model_json)
    return _set


# ─────────────────────────────────────────────────────────────────────────────
# Parsing — happy path
# ─────────────────────────────────────────────────────────────────────────────

class TestParseBatchResponse:

    def test_returns_correct_count(self, svc, mock_batch_converse):
        mock_batch_converse(BATCH_PAYLOAD)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert len(out.message_analyses) == 3

    def test_sentiment_labels_parsed(self, svc, mock_batch_converse):
        mock_batch_converse(BATCH_PAYLOAD)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert out.message_analyses[0].sentiment.label == "engaged"
        assert out.message_analyses[1].sentiment.label == "disengaged"
        assert out.message_analyses[2].sentiment.label == "distressed_upset"

    def test_sentiment_confidence_parsed(self, svc, mock_batch_converse):
        mock_batch_converse(BATCH_PAYLOAD)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert out.message_analyses[0].sentiment.confidence == 0.82
        assert out.message_analyses[2].sentiment.confidence == 0.95

    def test_sentiment_reason_parsed(self, svc, mock_batch_converse):
        mock_batch_converse(BATCH_PAYLOAD)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert "Client actively sought help" in out.message_analyses[0].sentiment.reason

    def test_risk_level_parsed(self, svc, mock_batch_converse):
        mock_batch_converse(BATCH_PAYLOAD)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert out.message_analyses[0].risk.level == "low"
        assert out.message_analyses[1].risk.level == "medium"
        assert out.message_analyses[2].risk.level == "high"

    def test_risk_indicators_parsed(self, svc, mock_batch_converse):
        mock_batch_converse(BATCH_PAYLOAD)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert out.message_analyses[0].risk.indicators == []
        assert "client request dismissed" in out.message_analyses[1].risk.indicators
        assert len(out.message_analyses[2].risk.indicators) == 2

    def test_breakdown_detected_parsed(self, svc, mock_batch_converse):
        mock_batch_converse(BATCH_PAYLOAD)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert out.message_analyses[0].breakdown.detected is False
        assert out.message_analyses[2].breakdown.detected is True

    def test_breakdown_reasons_cleared_when_not_detected(self, svc, mock_batch_converse):
        payload = {
            "messages": [
                _msg_analysis(0, breakdown_detected=False, breakdown_reasons=["should be cleared"])
            ]
        }
        mock_batch_converse(payload)
        out = svc.analyse_batch([_make_message()])
        assert out.message_analyses[0].breakdown.reasons == []

    def test_outcome_parsed(self, svc, mock_batch_converse):
        mock_batch_converse(BATCH_PAYLOAD)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert out.message_analyses[0].outcome == "pending"
        assert out.message_analyses[2].outcome == "unresolved"

    def test_recommended_action_parsed(self, svc, mock_batch_converse):
        mock_batch_converse(BATCH_PAYLOAD)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert out.message_analyses[0].recommended_action is None
        assert out.message_analyses[2].recommended_action == "Escalate to coordinator."

    def test_messages_sorted_by_index(self, svc, mock_batch_converse):
        """Model returns out-of-order — should be sorted by index."""
        payload = {
            "messages": [
                _msg_analysis(2, "distressed_upset"),
                _msg_analysis(0, "engaged"),
                _msg_analysis(1, "neutral"),
            ]
        }
        mock_batch_converse(payload)
        out = svc.analyse_batch(_make_batch_request().messages)
        assert out.message_analyses[0].sentiment.label == "engaged"
        assert out.message_analyses[1].sentiment.label == "neutral"
        assert out.message_analyses[2].sentiment.label == "distressed_upset"


# ─────────────────────────────────────────────────────────────────────────────
# Parsing — fallbacks
# ─────────────────────────────────────────────────────────────────────────────

class TestParseBatchFallbacks:

    def test_unknown_sentiment_label_falls_back_to_neutral(self, svc, mock_batch_converse):
        payload = {"messages": [_msg_analysis(0, sentiment_label="angry")]}
        mock_batch_converse(payload)
        out = svc.analyse_batch([_make_message()])
        assert out.message_analyses[0].sentiment.label == "neutral"

    def test_unknown_risk_level_falls_back_to_low(self, svc, mock_batch_converse):
        payload = {"messages": [_msg_analysis(0, risk_level="extreme")]}
        mock_batch_converse(payload)
        out = svc.analyse_batch([_make_message()])
        assert out.message_analyses[0].risk.level == "low"

    def test_unknown_outcome_falls_back_to_pending(self, svc, mock_batch_converse):
        payload = {"messages": [_msg_analysis(0, outcome="escalated")]}
        mock_batch_converse(payload)
        out = svc.analyse_batch([_make_message()])
        assert out.message_analyses[0].outcome == "pending"

    def test_null_recommended_action_string_becomes_none(self, svc, mock_batch_converse):
        payload = {"messages": [_msg_analysis(0, recommended_action="null")]}
        mock_batch_converse(payload)
        out = svc.analyse_batch([_make_message()])
        assert out.message_analyses[0].recommended_action is None

    def test_empty_recommended_action_becomes_none(self, svc, mock_batch_converse):
        payload = {"messages": [_msg_analysis(0, recommended_action="")]}
        mock_batch_converse(payload)
        out = svc.analyse_batch([_make_message()])
        assert out.message_analyses[0].recommended_action is None

    def test_non_list_messages_field_returns_empty(self, svc, mock_batch_converse):
        mock_batch_converse({"messages": "not a list"})
        out = svc.analyse_batch([_make_message()])
        assert out.message_analyses == []

    def test_missing_messages_key_returns_empty(self, svc, mock_batch_converse):
        mock_batch_converse({})
        out = svc.analyse_batch([_make_message()])
        assert out.message_analyses == []

    def test_malformed_json_raises_value_error(self, svc):
        svc.client.converse.return_value = {
            "output": {"message": {"content": [{"text": "not valid json {{{"}]}}
        }
        with pytest.raises(ValueError, match="invalid JSON"):
            svc.analyse_batch([_make_message()])

    def test_markdown_fenced_json_is_stripped(self, svc):
        fenced = "```json\n" + json.dumps({"messages": [_msg_analysis(0)]}) + "\n```"
        svc.client.converse.return_value = {
            "output": {"message": {"content": [{"text": fenced}]}}
        }
        out = svc.analyse_batch([_make_message()])
        assert len(out.message_analyses) == 1


# ─────────────────────────────────────────────────────────────────────────────
# All 7 valid sentiment labels
# ─────────────────────────────────────────────────────────────────────────────

class TestAllSentimentLabels:
    @pytest.mark.parametrize("label", [
        "positive_satisfied",
        "neutral",
        "frustrated_dissatisfied",
        "distressed_upset",
        "confused_uncertain",
        "engaged",
        "disengaged",
    ])
    def test_valid_label_parsed(self, svc, mock_batch_converse, label):
        mock_batch_converse({"messages": [_msg_analysis(0, sentiment_label=label)]})
        out = svc.analyse_batch([_make_message()])
        assert out.message_analyses[0].sentiment.label == label


# ─────────────────────────────────────────────────────────────────────────────
# SentimentBatchService orchestration
# ─────────────────────────────────────────────────────────────────────────────

class TestSentimentBatchService:

    @pytest.fixture
    def batch_svc(self):
        with patch("app.services.bedrock_service.boto3"):
            svc = SentimentBatchService()
        return svc

    def _set_bedrock(self, batch_svc, model_json: dict):
        batch_svc.bedrock.client.converse.return_value = _bedrock_response(model_json)

    def test_response_has_correct_message_count(self, batch_svc):
        self._set_bedrock(batch_svc, BATCH_PAYLOAD)
        resp = batch_svc.analyse(_make_batch_request())
        assert len(resp.messages) == 3
        assert resp.messages_analysed == 3

    def test_response_preserves_role_and_text(self, batch_svc):
        self._set_bedrock(batch_svc, BATCH_PAYLOAD)
        resp = batch_svc.analyse(_make_batch_request())
        assert resp.messages[0].role == "client"
        assert resp.messages[0].text == "I need help."
        assert resp.messages[1].role == "support_worker"
        assert resp.messages[1].text == "Wait a moment."

    def test_period_start_is_earliest_timestamp(self, batch_svc):
        self._set_bedrock(batch_svc, BATCH_PAYLOAD)
        resp = batch_svc.analyse(_make_batch_request())
        assert resp.period_start == datetime.fromisoformat("2025-06-01T10:00:00+00:00")

    def test_period_end_is_latest_timestamp(self, batch_svc):
        self._set_bedrock(batch_svc, BATCH_PAYLOAD)
        resp = batch_svc.analyse(_make_batch_request())
        assert resp.period_end == datetime.fromisoformat("2025-06-01T10:02:00+00:00")

    def test_conversation_id_and_provider_id_echoed(self, batch_svc):
        self._set_bedrock(batch_svc, BATCH_PAYLOAD)
        resp = batch_svc.analyse(_make_batch_request())
        assert resp.conversation_id == "test_batch_conv"
        assert resp.provider_id == "test_org"

    def test_analysed_at_is_datetime(self, batch_svc):
        self._set_bedrock(batch_svc, BATCH_PAYLOAD)
        resp = batch_svc.analyse(_make_batch_request())
        assert isinstance(resp.analysed_at, datetime)

    def test_all_message_fields_present(self, batch_svc):
        self._set_bedrock(batch_svc, BATCH_PAYLOAD)
        resp = batch_svc.analyse(_make_batch_request())
        for msg in resp.messages:
            assert msg.sentiment is not None
            assert msg.risk is not None
            assert msg.breakdown is not None
            assert msg.outcome in ("resolved", "unresolved", "pending")

    def test_count_mismatch_uses_fallback(self, batch_svc):
        """Model returns 1 analysis for 3 messages — missing 2 should use fallback."""
        short_payload = {"messages": [_msg_analysis(0, "engaged")]}
        self._set_bedrock(batch_svc, short_payload)
        resp = batch_svc.analyse(_make_batch_request())
        assert len(resp.messages) == 3
        # index 0 gets real analysis
        assert resp.messages[0].sentiment.label == "engaged"
        # indices 1 and 2 get fallback
        assert resp.messages[1].sentiment.label == "neutral"
        assert resp.messages[1].sentiment.confidence == 0.0
        assert resp.messages[2].sentiment.confidence == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Schema validation
# ─────────────────────────────────────────────────────────────────────────────

class TestBatchRequestValidation:

    def test_empty_messages_list_raises(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SentimentBatchRequest(
                conversation_id="conv",
                provider_id="org",
                messages=[],
            )

    def test_over_50_messages_raises(self):
        import pydantic
        messages = [_make_message() for _ in range(51)]
        with pytest.raises(pydantic.ValidationError):
            SentimentBatchRequest(
                conversation_id="conv",
                provider_id="org",
                messages=messages,
            )

    def test_exactly_50_messages_is_valid(self):
        messages = [_make_message() for _ in range(50)]
        req = SentimentBatchRequest(
            conversation_id="conv",
            provider_id="org",
            messages=messages,
        )
        assert len(req.messages) == 50

    def test_single_message_is_valid(self):
        req = SentimentBatchRequest(
            conversation_id="conv",
            provider_id="org",
            messages=[_make_message()],
        )
        assert len(req.messages) == 1
