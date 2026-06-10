"""
Sena Communication Log Classifier — Unit Tests
No network calls. All Bedrock responses are mocked.

Run:
    pytest tests/test_unit.py -v
    pytest tests/test_unit.py -v -k "sentiment"   # run a specific group
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.services.bedrock_service import BedrockService, BedrockOutput
from app.services.classification_service import ClassificationService
from app.models.schemas import (
    ClassificationRequest,
    Message,
)
from app.core.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _bedrock_response(model_json: dict) -> dict:
    """Wraps a model payload in the Bedrock converse response envelope."""
    return {
        "output": {
            "message": {
                "content": [{"text": json.dumps(model_json)}]
            }
        }
    }


def _make_message(role="support_worker", text="Hello.", ts="2025-06-01T10:05:00Z") -> Message:
    return Message(role=role, text=text, timestamp=datetime.fromisoformat(ts.replace("Z", "+00:00")))


def _make_request(current_text="Hello.", history=None) -> ClassificationRequest:
    return ClassificationRequest(
        conversation_id="test_conv",
        provider_id="test_org",
        current_message=_make_message(text=current_text),
        history=history or [],
    )


NORMAL_PAYLOAD = {
    "classifications": [
        {"label": "normal", "confidence": 0.95, "reason": "Professional and respectful."}
    ],
    "sentiment": {
        "label": "positive_satisfied",
        "confidence": 0.88,
        "reason": "Client expressed gratitude."
    },
    "risk": {
        "level": "low",
        "indicators": [],
        "reason": "No risk indicators detected."
    },
    "breakdown": {"detected": False, "reasons": []},
    "outcome": "resolved",
    "recommended_action": None,
}


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    """BedrockService with boto3 patched out — never calls AWS."""
    with patch("app.services.bedrock_service.boto3") as mock_boto3:
        mock_boto3.client.return_value = MagicMock()
        service = BedrockService()
        yield service


@pytest.fixture
def mock_converse(svc):
    """Returns a helper that sets the next Bedrock response."""
    def _set(model_json: dict):
        svc.client.converse.return_value = _bedrock_response(model_json)
    return _set


# ─────────────────────────────────────────────────────────────────────────────
# Classifications parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestParseClassifications:
    def test_normal_label(self, svc, mock_converse):
        mock_converse(NORMAL_PAYLOAD)
        out = svc.classify(_make_message(), [])
        assert len(out.classifications) == 1
        assert out.classifications[0].label == "normal"
        assert out.classifications[0].confidence == 0.95
        assert "Professional" in out.classifications[0].reason

    def test_emergency_label(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "classifications": [
                {"label": "emergency", "confidence": 0.99, "reason": "Client expressed self-harm ideation."}
            ],
            "sentiment": {"label": "distressed_upset", "confidence": 0.97, "reason": "Severe distress."},
            "risk": {"level": "critical", "indicators": ["self-harm ideation"], "reason": "Immediate risk."},
            "outcome": "unresolved",
            "recommended_action": "Escalate to coordinator immediately.",
        })
        out = svc.classify(_make_message(), [])
        assert out.classifications[0].label == "emergency"
        assert out.classifications[0].confidence == 0.99

    def test_inappropriate_label(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "classifications": [
                {"label": "inappropriate", "confidence": 0.91, "reason": "Worker used dismissive language."}
            ],
            "sentiment": {"label": "frustrated_dissatisfied", "confidence": 0.85, "reason": "Client frustrated."},
            "risk": {"level": "medium", "indicators": ["worker dismissiveness"], "reason": "Risk of disengagement."},
            "outcome": "unresolved",
            "recommended_action": None,
        })
        out = svc.classify(_make_message(), [])
        assert out.classifications[0].label == "inappropriate"

    def test_multi_label_emergency_and_inappropriate(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "classifications": [
                {"label": "emergency", "confidence": 0.97, "reason": "Client injured, worker abandoned them."},
                {"label": "inappropriate", "confidence": 0.93, "reason": "Worker refused to help injured client."},
            ],
            "risk": {"level": "critical", "indicators": ["client injury", "worker abandonment"], "reason": "Critical."},
            "outcome": "unresolved",
            "recommended_action": "File incident report.",
        })
        out = svc.classify(_make_message(), [])
        assert len(out.classifications) == 2
        lbls = [c.label for c in out.classifications]
        assert "emergency" in lbls
        assert "inappropriate" in lbls

    def test_unknown_label_is_skipped(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "classifications": [
                {"label": "unknown_label", "confidence": 0.9, "reason": "Some reason."},
                {"label": "normal", "confidence": 0.8, "reason": "Professional."},
            ],
        })
        out = svc.classify(_make_message(), [])
        lbls = [c.label for c in out.classifications]
        assert "unknown_label" not in lbls
        assert "normal" in lbls

    def test_all_unknown_labels_raises(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "classifications": [
                {"label": "invalid_a", "confidence": 0.9, "reason": "x"},
                {"label": "invalid_b", "confidence": 0.8, "reason": "y"},
            ],
        })
        with pytest.raises(ValueError, match="No valid classification labels"):
            svc.classify(_make_message(), [])

    def test_empty_classifications_raises(self, svc, mock_converse):
        mock_converse({**NORMAL_PAYLOAD, "classifications": []})
        with pytest.raises(ValueError, match="no classifications"):
            svc.classify(_make_message(), [])


# ─────────────────────────────────────────────────────────────────────────────
# Sentiment parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestParseSentiment:
    @pytest.mark.parametrize("label", [
        "positive_satisfied",
        "neutral",
        "frustrated_dissatisfied",
        "distressed_upset",
        "confused_uncertain",
        "engaged",
        "disengaged",
    ])
    def test_all_valid_sentiment_labels(self, svc, mock_converse, label):
        mock_converse({
            **NORMAL_PAYLOAD,
            "sentiment": {"label": label, "confidence": 0.80, "reason": f"Participant is {label}."},
        })
        out = svc.classify(_make_message(), [])
        assert out.sentiment.label == label
        assert 0.0 <= out.sentiment.confidence <= 1.0
        assert len(out.sentiment.reason) > 0

    def test_unknown_sentiment_falls_back_to_neutral(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "sentiment": {"label": "angry", "confidence": 0.75, "reason": "Angry response."},
        })
        out = svc.classify(_make_message(), [])
        assert out.sentiment.label == "neutral"

    def test_missing_sentiment_section_falls_back(self, svc, mock_converse):
        payload = {k: v for k, v in NORMAL_PAYLOAD.items() if k != "sentiment"}
        mock_converse(payload)
        out = svc.classify(_make_message(), [])
        assert out.sentiment.label == "neutral"
        assert out.sentiment.confidence == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Risk parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestParseRisk:
    @pytest.mark.parametrize("level", ["low", "medium", "high", "critical"])
    def test_all_valid_risk_levels(self, svc, mock_converse, level):
        mock_converse({
            **NORMAL_PAYLOAD,
            "risk": {
                "level": level,
                "indicators": ["indicator A"] if level != "low" else [],
                "reason": f"Risk is {level}.",
            },
        })
        out = svc.classify(_make_message(), [])
        assert out.risk.level == level

    def test_risk_indicators_list(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "risk": {
                "level": "high",
                "indicators": ["participant distress", "missed supports", "escalating conflict"],
                "reason": "Multiple risk indicators present.",
            },
        })
        out = svc.classify(_make_message(), [])
        assert len(out.risk.indicators) == 3
        assert "participant distress" in out.risk.indicators

    def test_empty_indicators_for_low_risk(self, svc, mock_converse):
        mock_converse(NORMAL_PAYLOAD)
        out = svc.classify(_make_message(), [])
        assert out.risk.level == "low"
        assert out.risk.indicators == []

    def test_unknown_risk_level_falls_back_to_low(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "risk": {"level": "extreme", "indicators": [], "reason": "Very risky."},
        })
        out = svc.classify(_make_message(), [])
        assert out.risk.level == "low"

    def test_missing_risk_section_falls_back(self, svc, mock_converse):
        payload = {k: v for k, v in NORMAL_PAYLOAD.items() if k != "risk"}
        mock_converse(payload)
        out = svc.classify(_make_message(), [])
        assert out.risk.level == "low"

    def test_non_list_indicators_coerced_to_empty(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "risk": {"level": "medium", "indicators": "some string", "reason": "Risk present."},
        })
        out = svc.classify(_make_message(), [])
        assert out.risk.indicators == []


# ─────────────────────────────────────────────────────────────────────────────
# Breakdown parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestParseBreakdown:
    def test_breakdown_not_detected(self, svc, mock_converse):
        mock_converse(NORMAL_PAYLOAD)
        out = svc.classify(_make_message(), [])
        assert out.breakdown.detected is False
        assert out.breakdown.reasons == []

    def test_breakdown_detected_with_reasons(self, svc, mock_converse):
        mock_converse({
            **NORMAL_PAYLOAD,
            "breakdown": {
                "detected": True,
                "reasons": [
                    "Participant's question not adequately addressed",
                    "Repeated clarification requests by participant",
                ],
            },
        })
        out = svc.classify(_make_message(), [])
        assert out.breakdown.detected is True
        assert len(out.breakdown.reasons) == 2
        assert "Repeated clarification requests by participant" in out.breakdown.reasons

    def test_breakdown_false_clears_reasons(self, svc, mock_converse):
        """Even if model accidentally sends reasons when detected=false, we clear them."""
        mock_converse({
            **NORMAL_PAYLOAD,
            "breakdown": {"detected": False, "reasons": ["should be cleared"]},
        })
        out = svc.classify(_make_message(), [])
        assert out.breakdown.detected is False
        assert out.breakdown.reasons == []

    def test_missing_breakdown_section_falls_back(self, svc, mock_converse):
        payload = {k: v for k, v in NORMAL_PAYLOAD.items() if k != "breakdown"}
        mock_converse(payload)
        out = svc.classify(_make_message(), [])
        assert out.breakdown.detected is False
        assert out.breakdown.reasons == []


# ─────────────────────────────────────────────────────────────────────────────
# Outcome parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestParseOutcome:
    @pytest.mark.parametrize("outcome", ["resolved", "unresolved", "pending"])
    def test_all_valid_outcomes(self, svc, mock_converse, outcome):
        mock_converse({**NORMAL_PAYLOAD, "outcome": outcome})
        out = svc.classify(_make_message(), [])
        assert out.outcome == outcome

    def test_unknown_outcome_falls_back_to_pending(self, svc, mock_converse):
        mock_converse({**NORMAL_PAYLOAD, "outcome": "escalated"})
        out = svc.classify(_make_message(), [])
        assert out.outcome == "pending"

    def test_missing_outcome_falls_back_to_pending(self, svc, mock_converse):
        payload = {k: v for k, v in NORMAL_PAYLOAD.items() if k != "outcome"}
        mock_converse(payload)
        out = svc.classify(_make_message(), [])
        assert out.outcome == "pending"


# ─────────────────────────────────────────────────────────────────────────────
# Recommended action parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestParseRecommendedAction:
    def test_null_json_value(self, svc, mock_converse):
        mock_converse({**NORMAL_PAYLOAD, "recommended_action": None})
        out = svc.classify(_make_message(), [])
        assert out.recommended_action is None

    def test_string_null_becomes_none(self, svc, mock_converse):
        mock_converse({**NORMAL_PAYLOAD, "recommended_action": "null"})
        out = svc.classify(_make_message(), [])
        assert out.recommended_action is None

    def test_empty_string_becomes_none(self, svc, mock_converse):
        mock_converse({**NORMAL_PAYLOAD, "recommended_action": ""})
        out = svc.classify(_make_message(), [])
        assert out.recommended_action is None

    def test_valid_action_string(self, svc, mock_converse):
        mock_converse({**NORMAL_PAYLOAD, "recommended_action": "Escalate to coordinator for immediate review."})
        out = svc.classify(_make_message(), [])
        assert out.recommended_action == "Escalate to coordinator for immediate review."

    def test_missing_key_becomes_none(self, svc, mock_converse):
        payload = {k: v for k, v in NORMAL_PAYLOAD.items() if k != "recommended_action"}
        mock_converse(payload)
        out = svc.classify(_make_message(), [])
        assert out.recommended_action is None


# ─────────────────────────────────────────────────────────────────────────────
# JSON parsing edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestJsonParsing:
    def test_markdown_fenced_json_is_stripped(self, svc):
        fenced = "```json\n" + json.dumps(NORMAL_PAYLOAD) + "\n```"
        svc.client.converse.return_value = {
            "output": {"message": {"content": [{"text": fenced}]}}
        }
        out = svc.classify(_make_message(), [])
        assert out.classifications[0].label == "normal"

    def test_malformed_json_raises_value_error(self, svc):
        svc.client.converse.return_value = {
            "output": {"message": {"content": [{"text": "not valid json {{{"}]}}
        }
        with pytest.raises(ValueError, match="invalid JSON"):
            svc.classify(_make_message(), [])

    def test_unexpected_bedrock_response_structure_raises(self, svc):
        svc.client.converse.return_value = {"unexpected_key": "no output"}
        with pytest.raises(ValueError, match="Could not extract text"):
            svc.classify(_make_message(), [])


# ─────────────────────────────────────────────────────────────────────────────
# ClassificationService orchestration
# ─────────────────────────────────────────────────────────────────────────────

class TestClassificationService:
    """Tests ClassificationService.classify() with a mocked BedrockService."""

    @pytest.fixture
    def cls_svc(self):
        with patch("app.services.bedrock_service.boto3"):
            svc = ClassificationService()
        return svc

    def _set_bedrock(self, cls_svc, model_json: dict):
        cls_svc.bedrock.client.converse.return_value = _bedrock_response(model_json)

    def test_full_response_fields_present(self, cls_svc):
        self._set_bedrock(cls_svc, NORMAL_PAYLOAD)
        req = _make_request()
        resp = cls_svc.classify(req)
        assert resp.conversation_id == "test_conv"
        assert resp.provider_id == "test_org"
        assert isinstance(resp.is_uncertain, bool)
        assert len(resp.classifications) >= 1
        assert resp.sentiment is not None
        assert resp.risk is not None
        assert resp.breakdown is not None
        assert resp.outcome in ("resolved", "unresolved", "pending")
        assert resp.messages_analysed >= 1

    def test_messages_analysed_no_history(self, cls_svc):
        self._set_bedrock(cls_svc, NORMAL_PAYLOAD)
        req = _make_request()
        resp = cls_svc.classify(req)
        assert resp.messages_analysed == 1

    def test_messages_analysed_with_history(self, cls_svc):
        self._set_bedrock(cls_svc, NORMAL_PAYLOAD)
        history = [_make_message("client", "Hi") for _ in range(3)]
        req = _make_request(history=history)
        resp = cls_svc.classify(req)
        assert resp.messages_analysed == 4  # 3 history + 1 current

    def test_history_trimmed_to_limit(self, cls_svc):
        self._set_bedrock(cls_svc, NORMAL_PAYLOAD)
        history = [_make_message("client", f"msg {i}") for i in range(10)]
        req = _make_request(history=history)
        resp = cls_svc.classify(req)
        # Trimmed to settings.CONVERSATION_HISTORY_LIMIT + 1 current
        assert resp.messages_analysed == settings.CONVERSATION_HISTORY_LIMIT + 1

    def test_is_uncertain_true_when_all_confidence_below_threshold(self, cls_svc):
        self._set_bedrock(cls_svc, {
            **NORMAL_PAYLOAD,
            "classifications": [
                {"label": "normal", "confidence": 0.2, "reason": "Low confidence."},
            ],
        })
        resp = cls_svc.classify(_make_request())
        assert resp.is_uncertain is True

    def test_is_uncertain_false_when_any_confidence_above_threshold(self, cls_svc):
        self._set_bedrock(cls_svc, {
            **NORMAL_PAYLOAD,
            "classifications": [
                {"label": "emergency", "confidence": 0.9, "reason": "High confidence."},
            ],
        })
        resp = cls_svc.classify(_make_request())
        assert resp.is_uncertain is False

    def test_is_uncertain_boundary_at_threshold(self, cls_svc):
        """Confidence exactly at threshold is NOT uncertain (< threshold triggers it)."""
        self._set_bedrock(cls_svc, {
            **NORMAL_PAYLOAD,
            "classifications": [
                {"label": "normal", "confidence": settings.CONFIDENCE_THRESHOLD, "reason": "At boundary."},
            ],
        })
        resp = cls_svc.classify(_make_request())
        assert resp.is_uncertain is False

    def test_multi_label_one_high_confidence_not_uncertain(self, cls_svc):
        self._set_bedrock(cls_svc, {
            **NORMAL_PAYLOAD,
            "classifications": [
                {"label": "emergency", "confidence": 0.15, "reason": "Low."},
                {"label": "inappropriate", "confidence": 0.85, "reason": "High."},
            ],
        })
        resp = cls_svc.classify(_make_request())
        assert resp.is_uncertain is False

    def test_analysed_at_is_datetime(self, cls_svc):
        self._set_bedrock(cls_svc, NORMAL_PAYLOAD)
        resp = cls_svc.classify(_make_request())
        assert isinstance(resp.analysed_at, datetime)

    def test_conversation_id_and_provider_id_echoed(self, cls_svc):
        self._set_bedrock(cls_svc, NORMAL_PAYLOAD)
        req = ClassificationRequest(
            conversation_id="conv_XYZ",
            provider_id="provider_ABC",
            current_message=_make_message(),
        )
        resp = cls_svc.classify(req)
        assert resp.conversation_id == "conv_XYZ"
        assert resp.provider_id == "provider_ABC"


# ─────────────────────────────────────────────────────────────────────────────
# SCOPE example scenarios (end-to-end with mocks)
# ─────────────────────────────────────────────────────────────────────────────

class TestScopeExamples:
    """Validates the exact scenarios from SCOPE.md against expected output shape."""

    @pytest.fixture
    def cls_svc(self):
        with patch("app.services.bedrock_service.boto3"):
            svc = ClassificationService()
        return svc

    def test_scope_example_1_low_risk_resolved(self, cls_svc):
        """Participant: transport not received. Worker commits to check. → low, resolved."""
        cls_svc.bedrock.client.converse.return_value = _bedrock_response({
            "classifications": [{"label": "normal", "confidence": 0.92, "reason": "Worker responded professionally."}],
            "sentiment": {"label": "frustrated_dissatisfied", "confidence": 0.78, "reason": "Participant frustrated about missing transport."},
            "risk": {"level": "low", "indicators": [], "reason": "Worker acknowledged and committed to follow up."},
            "breakdown": {"detected": False, "reasons": []},
            "outcome": "resolved",
            "recommended_action": None,
        })
        req = ClassificationRequest(
            conversation_id="scope_ex1",
            provider_id="org_001",
            current_message=_make_message("support_worker", "Sorry about that. I'll check and get back to you today."),
            history=[_make_message("client", "I haven't received my transport support this week.")],
        )
        resp = cls_svc.classify(req)
        assert resp.classifications[0].label == "normal"
        assert resp.sentiment.label == "frustrated_dissatisfied"
        assert resp.risk.level == "low"
        assert resp.breakdown.detected is False
        assert resp.outcome == "resolved"
        assert resp.recommended_action is None

    def test_scope_example_2_communication_breakdown(self, cls_svc):
        """Repeated circular answers → breakdown detected, medium risk, unresolved."""
        cls_svc.bedrock.client.converse.return_value = _bedrock_response({
            "classifications": [{"label": "inappropriate", "confidence": 0.80, "reason": "Worker failed to address participant's question."}],
            "sentiment": {"label": "frustrated_dissatisfied", "confidence": 0.85, "reason": "Participant frustrated by repeated non-answers."},
            "risk": {"level": "medium", "indicators": ["repeated unaddressed questions"], "reason": "Participant's needs not being met."},
            "breakdown": {
                "detected": True,
                "reasons": ["Participant's question not adequately addressed", "Conversation becoming circular without resolution"],
            },
            "outcome": "unresolved",
            "recommended_action": "Follow up to ensure participant questions are answered.",
        })
        req = ClassificationRequest(
            conversation_id="scope_ex2",
            provider_id="org_001",
            current_message=_make_message("support_worker", "It's in the documents."),
            history=[
                _make_message("client", "Can you explain why my support hours changed?"),
                _make_message("support_worker", "Please check your plan."),
                _make_message("client", "I already did, but I don't understand."),
            ],
        )
        resp = cls_svc.classify(req)
        assert resp.sentiment.label == "frustrated_dissatisfied"
        assert resp.risk.level == "medium"
        assert resp.breakdown.detected is True
        assert len(resp.breakdown.reasons) == 2
        assert resp.outcome == "unresolved"
        assert resp.recommended_action is not None

    def test_scope_example_3_high_risk_distressed(self, cls_svc):
        """Overwhelmed participant → high risk, distressed, recommended_action set."""
        cls_svc.bedrock.client.converse.return_value = _bedrock_response({
            "classifications": [{"label": "normal", "confidence": 0.75, "reason": "Worker responded by escalating."}],
            "sentiment": {"label": "distressed_upset", "confidence": 0.93, "reason": "Participant expressed feeling overwhelmed and unable to cope."},
            "risk": {"level": "high", "indicators": ["participant expressing overwhelm", "missed support impacting wellbeing"], "reason": "Participant at risk without adequate support."},
            "breakdown": {"detected": False, "reasons": []},
            "outcome": "pending",
            "recommended_action": "Escalate to coordinator for review.",
        })
        req = ClassificationRequest(
            conversation_id="scope_ex3",
            provider_id="org_001",
            current_message=_make_message("support_worker", "I'll notify the coordinator immediately."),
            history=[_make_message("client", "I'm feeling overwhelmed and don't know how I'll manage without support this week.")],
        )
        resp = cls_svc.classify(req)
        assert resp.sentiment.label == "distressed_upset"
        assert resp.risk.level == "high"
        assert len(resp.risk.indicators) >= 1
        assert resp.breakdown.detected is False
        assert resp.recommended_action == "Escalate to coordinator for review."
