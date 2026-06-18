"""
Sena Communication Log — Batch Sentiment Integration Tests
Hits the locally running FastAPI server. Real AWS Bedrock is called.

Run:
    uvicorn app.main:app --reload --port 8000   (terminal 1)
    pytest tests/test_batch.py -v               (terminal 2)

Against deployed URL:
    $env:BASE_URL = "https://your-deployed-url.com"
    $env:API_KEY  = "your-key"
    pytest tests/test_batch.py -v
"""

import os
import pytest
import requests

_BASE = os.getenv("BASE_URL", "http://localhost:8000")
BASE_URL = _BASE.rstrip("/") + "/api/v1"
API_KEY = os.getenv("API_KEY", "")

_VALID_SENTIMENT_LABELS = {
    "positive_satisfied", "neutral", "frustrated_dissatisfied",
    "distressed_upset", "confused_uncertain", "engaged", "disengaged",
}
_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}
_VALID_OUTCOMES = {"resolved", "unresolved", "pending"}


# ── Builders ───────────────────────────────────────────────────────────────────

def msg(role, text, ts):
    return {"role": role, "text": text, "timestamp": ts}


def batch_payload(messages, conv_id="test_batch_001"):
    return {
        "conversation_id": conv_id,
        "provider_id": "test_org_001",
        "messages": messages,
        "metadata": {"shift_id": "shift_001"},
    }


def post_batch(body):
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    return requests.post(f"{BASE_URL}/sentiment-batch", json=body, headers=headers)


# ── Shared structural assertion ────────────────────────────────────────────────

def assert_valid_batch_response(body, expected_count):
    """Full contract check for /sentiment-batch — every integration test calls this."""
    assert "conversation_id" in body
    assert "provider_id" in body
    assert "messages_analysed" in body
    assert body["messages_analysed"] == expected_count
    assert "period_start" in body
    assert "period_end" in body
    assert "analysed_at" in body

    assert isinstance(body["messages"], list)
    assert len(body["messages"]) == expected_count

    for i, m in enumerate(body["messages"]):
        assert m["role"] in ("support_worker", "client"),     f"[{i}] invalid role"
        assert isinstance(m["text"], str) and len(m["text"]) > 0, f"[{i}] text missing"
        assert "timestamp" in m,                               f"[{i}] timestamp missing"

        # sentiment
        s = m["sentiment"]
        assert s["label"] in _VALID_SENTIMENT_LABELS,         f"[{i}] invalid sentiment label: {s['label']}"
        assert 0.0 <= s["confidence"] <= 1.0,                 f"[{i}] confidence out of range"
        assert isinstance(s["reason"], str) and s["reason"],  f"[{i}] sentiment reason empty"

        # risk
        r = m["risk"]
        assert r["level"] in _VALID_RISK_LEVELS,              f"[{i}] invalid risk level: {r['level']}"
        assert isinstance(r["indicators"], list),              f"[{i}] indicators not a list"
        assert isinstance(r["reason"], str) and r["reason"],  f"[{i}] risk reason empty"

        # breakdown
        bd = m["breakdown"]
        assert isinstance(bd["detected"], bool),               f"[{i}] breakdown.detected not bool"
        assert isinstance(bd["reasons"], list),                f"[{i}] breakdown.reasons not list"
        if not bd["detected"]:
            assert bd["reasons"] == [],                        f"[{i}] reasons must be empty when not detected"

        # outcome
        assert m["outcome"] in _VALID_OUTCOMES,               f"[{i}] invalid outcome: {m['outcome']}"

        # recommended_action
        assert m["recommended_action"] is None or isinstance(m["recommended_action"], str), \
            f"[{i}] recommended_action must be string or null"


# ── Structure ──────────────────────────────────────────────────────────────────

class TestBatchStructure:

    def test_single_message_batch(self):
        messages = [msg("client", "I need help with transport today.", "2025-06-01T10:00:00Z")]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        assert_valid_batch_response(r.json(), 1)

    def test_three_message_batch(self):
        messages = [
            msg("client",         "I need help getting to the bathroom.",            "2025-06-01T10:00:00Z"),
            msg("support_worker", "Wait, I'm busy.",                                 "2025-06-01T10:01:00Z"),
            msg("client",         "Please, it hurts.",                               "2025-06-01T10:02:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        assert_valid_batch_response(r.json(), 3)

    def test_message_count_equals_input(self):
        messages = [
            msg("client",         f"Message {i}.", f"2025-06-01T10:{i:02d}:00Z")
            for i in range(5)
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert len(body["messages"]) == 5

    def test_role_and_text_preserved_in_response(self):
        messages = [
            msg("client",         "I need help.", "2025-06-01T10:00:00Z"),
            msg("support_worker", "On my way.",   "2025-06-01T10:01:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert body["messages"][0]["role"] == "client"
        assert body["messages"][0]["text"] == "I need help."
        assert body["messages"][1]["role"] == "support_worker"

    def test_provider_id_echoed(self):
        messages = [msg("client", "Hello.", "2025-06-01T10:00:00Z")]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        assert r.json()["provider_id"] == "test_org_001"

    def test_period_start_and_end_present(self):
        messages = [
            msg("client",         "First message.",  "2025-06-01T10:00:00Z"),
            msg("support_worker", "Last message.",   "2025-06-01T10:05:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert "period_start" in body
        assert "period_end" in body


# ── Scenarios ──────────────────────────────────────────────────────────────────

class TestBatchScenarios:

    def test_normal_conversation_all_fields_present(self):
        messages = [
            msg("support_worker", "Good morning! How are you feeling today?",     "2025-06-01T10:00:00Z"),
            msg("client",         "I'm doing okay, thanks for coming.",            "2025-06-01T10:01:00Z"),
            msg("support_worker", "Great. Ready to help whenever you need.",       "2025-06-01T10:02:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert_valid_batch_response(body, 3)

    def test_inappropriate_worker_behaviour_flags_risk(self):
        messages = [
            msg("client",         "I need help getting to the bathroom.",                          "2025-06-01T10:00:00Z"),
            msg("support_worker", "Wait, I'm busy.",                                               "2025-06-01T10:01:00Z"),
            msg("client",         "Please, it's urgent.",                                          "2025-06-01T10:02:00Z"),
            msg("support_worker", "I don't want to deal with you. Just do what I say.",            "2025-06-01T10:03:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert_valid_batch_response(body, 4)
        risk_levels = [m["risk"]["level"] for m in body["messages"]]
        assert any(l in ("medium", "high", "critical") for l in risk_levels)

    def test_distressed_client_triggers_high_risk(self):
        messages = [
            msg("client",         "I'm feeling overwhelmed. I don't know how I'll cope without support.", "2025-06-01T10:00:00Z"),
            msg("support_worker", "I'll notify the coordinator immediately.",                              "2025-06-01T10:01:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert_valid_batch_response(body, 2)
        # first message (distressed client) should be high/critical risk
        assert body["messages"][0]["risk"]["level"] in ("high", "critical")
        assert body["messages"][0]["sentiment"]["label"] in ("distressed_upset", "frustrated_dissatisfied")

    def test_communication_breakdown_detected(self):
        messages = [
            msg("client",         "Can you explain why my support hours changed?",  "2025-06-01T10:00:00Z"),
            msg("support_worker", "Please check your plan.",                         "2025-06-01T10:01:00Z"),
            msg("client",         "I already did. I still don't understand.",        "2025-06-01T10:02:00Z"),
            msg("support_worker", "It's in the documents.",                          "2025-06-01T10:03:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert_valid_batch_response(body, 4)
        breakdown_flags = [m["breakdown"]["detected"] for m in body["messages"]]
        assert any(breakdown_flags)

    def test_high_risk_message_has_recommended_action(self):
        messages = [
            msg("client", "I don't want to live anymore. I've been thinking about hurting myself.", "2025-06-01T10:00:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert_valid_batch_response(body, 1)
        m = body["messages"][0]
        assert m["risk"]["level"] in ("high", "critical")
        assert m["recommended_action"] is not None and len(m["recommended_action"]) > 0

    def test_resolved_conversation_outcome(self):
        messages = [
            msg("client",         "I haven't received my transport support this week.",        "2025-06-01T10:00:00Z"),
            msg("support_worker", "Sorry about that. I'll check and get back to you today.",   "2025-06-01T10:01:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert_valid_batch_response(body, 2)
        outcomes = [m["outcome"] for m in body["messages"]]
        assert any(o in ("resolved", "pending") for o in outcomes)

    def test_positive_client_sentiment(self):
        messages = [
            msg("client", "Thank you so much, that was exactly what I needed.", "2025-06-01T10:00:00Z"),
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        body = r.json()
        assert_valid_batch_response(body, 1)
        assert body["messages"][0]["sentiment"]["label"] in ("positive_satisfied", "engaged")


# ── Validation errors ──────────────────────────────────────────────────────────

class TestBatchValidation:

    def test_empty_messages_list_returns_422(self):
        r = post_batch({"conversation_id": "conv", "provider_id": "org", "messages": []})
        assert r.status_code == 422

    def test_over_50_messages_returns_422(self):
        messages = [
            msg("client", f"Message {i}.", f"2025-06-01T{10 + i // 60:02d}:{i % 60:02d}:00Z")
            for i in range(51)
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 422

    def test_missing_conversation_id_returns_422(self):
        r = post_batch({
            "provider_id": "org",
            "messages": [msg("client", "Hello.", "2025-06-01T10:00:00Z")],
        })
        assert r.status_code == 422

    def test_missing_provider_id_returns_422(self):
        r = post_batch({
            "conversation_id": "conv",
            "messages": [msg("client", "Hello.", "2025-06-01T10:00:00Z")],
        })
        assert r.status_code == 422

    def test_invalid_role_returns_422(self):
        r = post_batch(batch_payload([
            msg("manager", "Hello.", "2025-06-01T10:00:00Z")
        ]))
        assert r.status_code == 422

    def test_invalid_timestamp_format_returns_422(self):
        r = post_batch(batch_payload([
            {"role": "client", "text": "Hello.", "timestamp": "01-06-2025"}
        ]))
        assert r.status_code == 422

    def test_empty_text_returns_422(self):
        r = post_batch(batch_payload([
            msg("client", "", "2025-06-01T10:00:00Z")
        ]))
        assert r.status_code == 422

    def test_missing_messages_key_returns_422(self):
        r = post_batch({"conversation_id": "conv", "provider_id": "org"})
        assert r.status_code == 422

    def test_exactly_50_messages_accepted(self):
        messages = [
            msg("client" if i % 2 == 0 else "support_worker",
                f"Message {i}.",
                f"2025-06-01T{10 + i // 60:02d}:{i % 60:02d}:00Z")
            for i in range(50)
        ]
        r = post_batch(batch_payload(messages))
        assert r.status_code == 200
        assert r.json()["messages_analysed"] == 50
