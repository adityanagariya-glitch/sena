"""
Sena Communication Log Classifier — Integration Tests
Hits the locally running FastAPI server. Real AWS Bedrock is called.

Run:
    uvicorn app.main:app --reload --port 8000   (terminal 1)
    pytest tests/test_classify.py -v             (terminal 2)

Against deployed URL:
    $env:BASE_URL = "https://your-deployed-url.com"
    $env:API_KEY  = "your-key"
    pytest tests/test_classify.py -v
"""

import os
import pytest
import requests

_BASE = os.getenv("BASE_URL", "http://localhost:8000")
BASE_URL = _BASE.rstrip("/") + "/api/v1"
HEALTH_URL = _BASE.rstrip("/") + "/health"
API_KEY = os.getenv("API_KEY", "")

_VALID_SENTIMENT_LABELS = {
    "positive_satisfied", "neutral", "frustrated_dissatisfied",
    "distressed_upset", "confused_uncertain", "engaged", "disengaged",
}
_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}
_VALID_OUTCOMES = {"resolved", "unresolved", "pending"}
_VALID_LABELS = {"emergency", "inappropriate", "normal"}


# ── Builders ───────────────────────────────────────────────────────────────────

def msg(role, text, ts="2025-06-01T10:05:00Z"):
    return {"role": role, "text": text, "timestamp": ts}


def payload(current_text, current_role="support_worker", history=None, conv_id="test_conv_001"):
    return {
        "conversation_id": conv_id,
        "provider_id": "test_org_001",
        "current_message": msg(current_role, current_text),
        "history": history or [],
        "metadata": {"shift_id": "shift_001", "client_id": "client_001", "worker_id": "worker_001"},
    }


def post(body):
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    return requests.post(f"{BASE_URL}/classify", json=body, headers=headers)


def labels(body):
    return [c["label"] for c in body["classifications"]]


# ── Shared structural assertions ───────────────────────────────────────────────

def assert_valid_response(body):
    """Full contract check — every integration test calls this."""
    # Top-level fields
    assert "conversation_id" in body
    assert "provider_id" in body
    assert isinstance(body["is_uncertain"], bool)
    assert isinstance(body["messages_analysed"], int) and body["messages_analysed"] >= 1
    assert "analysed_at" in body

    # classifications
    assert isinstance(body["classifications"], list) and len(body["classifications"]) >= 1
    for c in body["classifications"]:
        assert c["label"] in _VALID_LABELS
        assert 0.0 <= c["confidence"] <= 1.0
        assert isinstance(c["reason"], str) and len(c["reason"]) > 0

    # sentiment
    s = body["sentiment"]
    assert s["label"] in _VALID_SENTIMENT_LABELS
    assert 0.0 <= s["confidence"] <= 1.0
    assert isinstance(s["reason"], str) and len(s["reason"]) > 0

    # risk
    r = body["risk"]
    assert r["level"] in _VALID_RISK_LEVELS
    assert isinstance(r["indicators"], list)
    assert isinstance(r["reason"], str) and len(r["reason"]) > 0

    # breakdown
    bd = body["breakdown"]
    assert isinstance(bd["detected"], bool)
    assert isinstance(bd["reasons"], list)
    if not bd["detected"]:
        assert bd["reasons"] == []

    # outcome
    assert body["outcome"] in _VALID_OUTCOMES

    # recommended_action — string or null
    assert body["recommended_action"] is None or isinstance(body["recommended_action"], str)


# ── Health ─────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self):
        r = requests.get(HEALTH_URL)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "model" in body


# ── Normal conversations ───────────────────────────────────────────────────────

class TestNormal:
    def test_professional_greeting(self):
        r = post(payload(
            "Good morning! I'm here for your shift. How are you feeling today?",
            history=[msg("client", "I'm doing okay, thank you for coming.", "2025-06-01T10:03:00Z")]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "normal" in labels(body)
        assert body["messages_analysed"] == 2

    def test_first_message_no_history(self):
        r = post(payload("Hi, I'm your support worker today. Ready to help whenever you need."))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "normal" in labels(body)
        assert body["messages_analysed"] == 1

    def test_routine_task_completion(self):
        r = post(payload(
            "I've finished the morning routine. Everything went smoothly.",
            history=[msg("client", "Thanks, that was very helpful.", "2025-06-01T09:55:00Z")]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "normal" in labels(body)
        assert body["risk"]["level"] in ("low", "medium")

    def test_normal_never_combined_with_emergency_or_inappropriate(self):
        r = post(payload("All good today, have a great afternoon!"))
        assert r.status_code == 200
        body = r.json()
        lbls = labels(body)
        if "normal" in lbls:
            assert "emergency" not in lbls
            assert "inappropriate" not in lbls

    def test_provider_id_echoed(self):
        r = post(payload("Let me know if you need anything else."))
        assert r.status_code == 200
        assert r.json()["provider_id"] == "test_org_001"


# ── Sentiment coverage ─────────────────────────────────────────────────────────

class TestSentiment:
    def test_frustrated_client_transport_not_received(self):
        """SCOPE Example 1 — mild frustration → frustrated_dissatisfied."""
        r = post(payload(
            "Sorry about that. I'll check and get back to you today.",
            history=[msg("client", "I haven't received my transport support this week.", "2025-06-01T10:03:00Z")]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["sentiment"]["label"] in ("frustrated_dissatisfied", "neutral")
        assert body["risk"]["level"] in ("low", "medium")

    def test_distressed_client_overwhelmed(self):
        """SCOPE Example 3 — classify the client's distress message, not the worker's reply."""
        r = post(payload(
            "I'm feeling overwhelmed and don't know how I'll manage without support this week.",
            current_role="client",
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["sentiment"]["label"] in ("distressed_upset", "frustrated_dissatisfied")
        assert body["risk"]["level"] in ("high", "critical")
        assert body["recommended_action"] is not None

    def test_confused_client_plan_query(self):
        r = post(payload(
            "I already checked my plan but I still don't understand why my hours changed.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["sentiment"]["label"] in ("confused_uncertain", "frustrated_dissatisfied")

    def test_engaged_client(self):
        r = post(payload(
            "Yes, I understand. Let's work through the new schedule together.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["sentiment"]["label"] in ("engaged", "positive_satisfied", "neutral")

    def test_positive_satisfied_client(self):
        r = post(payload(
            "Thank you so much, that was exactly what I needed. I really appreciate your help.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["sentiment"]["label"] in ("positive_satisfied", "engaged")

    def test_disengaged_client(self):
        r = post(payload(
            "Fine. Whatever.",
            current_role="client",
            history=[
                msg("support_worker", "How are you feeling today? Did you sleep well?", "2025-06-01T09:00:00Z"),
                msg("support_worker", "Is there anything you'd like to do today?", "2025-06-01T09:05:00Z"),
            ]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["sentiment"]["label"] in ("disengaged", "neutral", "frustrated_dissatisfied")


# ── Risk levels ────────────────────────────────────────────────────────────────

class TestRisk:
    def test_low_risk_resolved(self):
        """SCOPE Example 1 — low risk, resolved outcome."""
        r = post(payload(
            "Sorry about that. I'll check and get back to you today.",
            history=[msg("client", "I haven't received my transport support this week.", "2025-06-01T10:03:00Z")]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["risk"]["level"] in ("low", "medium")
        assert body["outcome"] in ("resolved", "pending")

    def test_medium_risk_service_gap(self):
        """SCOPE Example 2 — medium risk with unresolved question."""
        r = post(payload(
            "It's in the documents.",
            history=[
                msg("client", "Can you explain why my support hours changed?", "2025-06-01T10:01:00Z"),
                msg("support_worker", "Please check your plan.", "2025-06-01T10:02:00Z"),
                msg("client", "I already did, but I don't understand.", "2025-06-01T10:03:00Z"),
            ]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["risk"]["level"] in ("medium", "high")

    def test_high_risk_sets_recommended_action(self):
        """High-risk conversations must have recommended_action."""
        r = post(payload(
            "I'm feeling overwhelmed and don't know how I'll manage without support this week.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        if body["risk"]["level"] in ("high", "critical"):
            assert body["recommended_action"] is not None
            assert len(body["recommended_action"]) > 0

    def test_critical_risk_self_harm(self):
        r = post(payload(
            "I don't want to live anymore. I've been thinking about hurting myself.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["risk"]["level"] in ("high", "critical")
        assert "emergency" in labels(body)
        assert body["recommended_action"] is not None

    def test_critical_risk_medical_emergency(self):
        r = post(payload(
            "I can't breathe properly and I have chest pain. I think something is wrong.",
            current_role="client",
            history=[msg("support_worker", "How are you feeling this morning?", "2025-06-01T10:03:00Z")]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["risk"]["level"] in ("high", "critical")
        assert "emergency" in labels(body)

    def test_indicators_list_populated_for_risk(self):
        r = post(payload(
            "I've been waiting for my support for three days and no one is answering.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        if body["risk"]["level"] in ("medium", "high", "critical"):
            assert len(body["risk"]["indicators"]) >= 1


# ── Emergency classification ───────────────────────────────────────────────────

class TestEmergency:
    def test_client_self_harm_ideation(self):
        r = post(payload(
            "I don't want to live anymore. I've been thinking about hurting myself.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "emergency" in labels(body)

    def test_medical_emergency_chest_pain(self):
        r = post(payload(
            "I can't breathe properly and I have chest pain. I think something is wrong.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "emergency" in labels(body)

    def test_worker_reports_physical_danger(self):
        r = post(payload(
            "The client is becoming very aggressive and threatening me physically. I don't feel safe.",
            current_role="support_worker"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "emergency" in labels(body)

    def test_client_reports_abuse(self):
        r = post(payload(
            "My support worker hit me yesterday and told me not to tell anyone.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "emergency" in labels(body)

    def test_emergency_has_recommended_action(self):
        r = post(payload(
            "I took too many of my pills. I don't feel well.",
            current_role="client"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "emergency" in labels(body)
        assert body["recommended_action"] is not None


# ── Inappropriate classification ───────────────────────────────────────────────

class TestInappropriate:
    def test_verbal_abuse_by_worker(self):
        r = post(payload(
            "I don't want to deal with you anymore. Just do what I say and stop complaining.",
            history=[
                msg("client", "I need help getting to the bathroom.", "2025-06-01T10:03:00Z"),
                msg("support_worker", "Wait, I'm busy.", "2025-06-01T10:04:00Z"),
            ]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "inappropriate" in labels(body)
        assert body["messages_analysed"] == 3

    def test_discriminatory_language(self):
        r = post(payload(
            "People like you are such a burden. You should just be grateful someone helps you."
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "inappropriate" in labels(body)

    def test_worker_ignores_urgent_medication_request(self):
        r = post(payload(
            "I already told you, I'll do it when I feel like it. Stop asking.",
            history=[
                msg("client", "Can you please help me with my medication?", "2025-06-01T09:00:00Z"),
                msg("client", "I really need my medication, it's been an hour.", "2025-06-01T10:00:00Z"),
            ]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "inappropriate" in labels(body)

    def test_coercive_behaviour(self):
        r = post(payload(
            "If you don't cooperate, I'll report you and they'll cut your funding. Your choice.",
            current_role="support_worker"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert "inappropriate" in labels(body)


# ── Multi-label ────────────────────────────────────────────────────────────────

class TestMultiLabel:
    def test_emergency_and_inappropriate_together(self):
        """Worker abandons injured client — SCOPE multi-label scenario."""
        r = post(payload(
            "I don't care if you're in pain, figure it out yourself. I'm leaving.",
            history=[msg("client", "Please don't leave, I fell and I think I broke something. I need help.", "2025-06-01T10:03:00Z")]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        lbls = labels(body)
        assert "emergency" in lbls
        assert "inappropriate" in lbls
        assert "normal" not in lbls

    def test_abuse_with_threat_of_harm(self):
        r = post(payload(
            "Shut up or I'll hurt you. You're nothing.",
            current_role="support_worker"
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        lbls = labels(body)
        assert "inappropriate" in lbls
        assert body["risk"]["level"] in ("high", "critical")


# ── Communication breakdown ────────────────────────────────────────────────────

class TestBreakdown:
    def test_repeated_unanswered_question(self):
        """SCOPE Example 2 — communication breakdown with circular conversation."""
        r = post(payload(
            "It's in the documents.",
            history=[
                msg("client", "Can you explain why my support hours changed?", "2025-06-01T10:01:00Z"),
                msg("support_worker", "Please check your plan.", "2025-06-01T10:02:00Z"),
                msg("client", "I already did, but I don't understand.", "2025-06-01T10:03:00Z"),
            ]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["breakdown"]["detected"] is True
        assert len(body["breakdown"]["reasons"]) >= 1
        assert body["outcome"] in ("unresolved", "pending")

    def test_no_breakdown_in_resolved_conversation(self):
        """Worker resolves the issue clearly — no breakdown expected."""
        r = post(payload(
            "That's a great question. Your hours changed because your plan was reviewed last month. Here's what changed and why…",
            history=[msg("client", "Can you explain why my support hours changed?", "2025-06-01T10:01:00Z")]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        if not body["breakdown"]["detected"]:
            assert body["breakdown"]["reasons"] == []

    def test_breakdown_sets_recommended_action(self):
        """Breakdown should generate a recommended_action."""
        r = post(payload(
            "Just read the email we sent.",
            history=[
                msg("client", "I never received any email about this.", "2025-06-01T10:00:00Z"),
                msg("support_worker", "We sent it last week.", "2025-06-01T10:01:00Z"),
                msg("client", "I checked and there's nothing.", "2025-06-01T10:02:00Z"),
                msg("support_worker", "It should be there.", "2025-06-01T10:03:00Z"),
                msg("client", "Can you just resend it or explain directly?", "2025-06-01T10:04:00Z"),
            ]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        if body["breakdown"]["detected"]:
            assert body["recommended_action"] is not None


# ── Outcome ────────────────────────────────────────────────────────────────────

class TestOutcome:
    def test_resolved_outcome(self):
        """SCOPE Example 1 — worker commits to fix, outcome = resolved."""
        r = post(payload(
            "Sorry about that. I'll check and get back to you today.",
            history=[msg("client", "I haven't received my transport support this week.", "2025-06-01T10:03:00Z")]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["outcome"] in ("resolved", "pending")

    def test_unresolved_outcome(self):
        r = post(payload(
            "It's in the documents.",
            history=[
                msg("client", "Can you explain why my support hours changed?", "2025-06-01T10:01:00Z"),
                msg("support_worker", "Please check your plan.", "2025-06-01T10:02:00Z"),
                msg("client", "I already did, but I don't understand.", "2025-06-01T10:03:00Z"),
            ]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["outcome"] in ("unresolved", "pending")

    def test_pending_outcome_follow_up_committed(self):
        r = post(payload(
            "I'll look into this tonight and call you back tomorrow with an update.",
            history=[msg("client", "My equipment hasn't been delivered and my plan starts Monday.", "2025-06-01T10:03:00Z")]
        ))
        assert r.status_code == 200
        body = r.json()
        assert_valid_response(body)
        assert body["outcome"] in ("pending", "resolved")


# ── History trimming ───────────────────────────────────────────────────────────

class TestHistoryTrimming:
    def test_10_messages_trimmed_to_5(self):
        history = [
            msg(
                "client" if i % 2 == 0 else "support_worker",
                f"Message {i}",
                f"2025-06-01T09:{i:02d}:00Z"
            )
            for i in range(10)
        ]
        r = post(payload("Everything is going fine today.", history=history))
        assert r.status_code == 200
        body = r.json()
        # messages_analysed = CONVERSATION_HISTORY_LIMIT (5) + current (1)
        assert body["messages_analysed"] == 6

    def test_fewer_messages_than_limit(self):
        history = [msg("client", "I need some help with transport.", "2025-06-01T10:03:00Z")]
        r = post(payload("Of course, let me help you with that.", history=history))
        assert r.status_code == 200
        body = r.json()
        assert body["messages_analysed"] == 2


# ── Validation errors ──────────────────────────────────────────────────────────

class TestValidation:
    def test_missing_conversation_id(self):
        r = post({"provider_id": "org_001", "current_message": msg("support_worker", "hello")})
        assert r.status_code == 422

    def test_missing_provider_id(self):
        r = post({"conversation_id": "conv_001", "current_message": msg("support_worker", "hello")})
        assert r.status_code == 422

    def test_missing_current_message(self):
        r = post({"conversation_id": "conv_001", "provider_id": "org_001"})
        assert r.status_code == 422

    def test_invalid_role(self):
        r = post(payload("hello", current_role="manager"))
        assert r.status_code == 422

    def test_invalid_timestamp_format(self):
        r = post({
            "conversation_id": "conv_001",
            "provider_id": "org_001",
            "current_message": {"role": "support_worker", "text": "hello", "timestamp": "01-06-2025"},
        })
        assert r.status_code == 422

    def test_empty_text(self):
        r = post(payload(""))
        assert r.status_code == 422

    def test_whitespace_only_text(self):
        r = post(payload("   "))
        assert r.status_code == 422
