"""
Sena Communication Log Classifier — Integration Tests
Hits the locally running FastAPI server at localhost:8000 by default.
Set BASE_URL env var to run against a deployed instance.
Real AWS Bedrock is called — ensure credentials are configured.

Run locally:
    uvicorn app.main:app --reload --port 8000   (in one terminal)
    pytest tests/test_classify.py -v             (in another terminal)

Run against deployed URL:
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


# ── Reusable payloads ──────────────────────────────────────────────────────────

def make_payload(current_text, current_role="support_worker", history=None, metadata=None):
    return {
        "conversation_id": "test_conv_001",
        "provider_id": "test_org_001",
        "current_message": {
            "role": current_role,
            "text": current_text,
            "timestamp": "2025-06-01T10:05:00Z"
        },
        "history": history or [],
        "metadata": metadata or {
            "shift_id": "shift_001",
            "client_id": "client_001",
            "worker_id": "worker_001"
        }
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_labels(response_json):
    return [c["label"] for c in response_json["classifications"]]

def get_confidences(response_json):
    return [c["confidence"] for c in response_json["classifications"]]

def auth_headers():
    return {"X-API-Key": API_KEY} if API_KEY else {}

def assert_valid_classification(c):
    assert c["label"] in ["emergency", "inappropriate", "normal"]
    assert 0.0 <= c["confidence"] <= 1.0
    assert isinstance(c["reason"], str)
    assert len(c["reason"]) > 0


# ── Health Check ───────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self):
        r = requests.get(HEALTH_URL)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "model" in body


# ── Normal Conversation ────────────────────────────────────────────────────────

class TestNormalClassification:
    def test_normal_professional_message(self):
        payload = make_payload(
            current_text="Good morning! I'm here for your shift. How are you feeling today?",
            current_role="support_worker",
            history=[
                {
                    "role": "client",
                    "text": "I'm doing okay, thank you for coming.",
                    "timestamp": "2025-06-01T10:03:00Z"
                }
            ]
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        assert body["conversation_id"] == "test_conv_001"
        assert body["provider_id"] == "test_org_001"
        assert "normal" in get_labels(body)
        assert body["messages_analysed"] == 2

        for c in body["classifications"]:
            assert_valid_classification(c)

    def test_normal_no_history(self):
        """First message in a conversation — no history sent."""
        payload = make_payload(
            current_text="Hi, I'm your support worker today. Ready to help whenever you need.",
            current_role="support_worker"
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        assert "normal" in get_labels(body)
        assert body["messages_analysed"] == 1


# ── Emergency Classification ───────────────────────────────────────────────────

class TestEmergencyClassification:
    def test_client_self_harm(self):
        payload = make_payload(
            current_text="I don't want to live anymore. I've been thinking about hurting myself.",
            current_role="client"
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        assert "emergency" in get_labels(body)
        for c in body["classifications"]:
            assert_valid_classification(c)

    def test_medical_emergency(self):
        payload = make_payload(
            current_text="I can't breathe properly and I have chest pain. I think something is wrong.",
            current_role="client",
            history=[
                {
                    "role": "support_worker",
                    "text": "How are you feeling this morning?",
                    "timestamp": "2025-06-01T10:03:00Z"
                }
            ]
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        assert "emergency" in get_labels(body)

    def test_worker_reports_danger(self):
        payload = make_payload(
            current_text="The client is becoming very aggressive and threatening me physically. I don't feel safe.",
            current_role="support_worker"
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        assert "emergency" in get_labels(body)


# ── Inappropriate Classification ───────────────────────────────────────────────

class TestInappropriateClassification:
    def test_verbal_abuse_by_worker(self):
        payload = make_payload(
            current_text="I don't want to deal with you anymore. Just do what I say and stop complaining.",
            current_role="support_worker",
            history=[
                {
                    "role": "client",
                    "text": "I need help getting to the bathroom.",
                    "timestamp": "2025-06-01T10:03:00Z"
                },
                {
                    "role": "support_worker",
                    "text": "Wait, I'm busy.",
                    "timestamp": "2025-06-01T10:04:00Z"
                }
            ]
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        assert "inappropriate" in get_labels(body)
        assert body["messages_analysed"] == 3

    def test_worker_ignoring_client_needs(self):
        payload = make_payload(
            current_text="I already told you, I'll do it when I feel like it. Stop asking.",
            current_role="support_worker",
            history=[
                {
                    "role": "client",
                    "text": "Can you please help me with my medication?",
                    "timestamp": "2025-06-01T09:00:00Z"
                },
                {
                    "role": "client",
                    "text": "I really need my medication, it's been an hour.",
                    "timestamp": "2025-06-01T10:00:00Z"
                }
            ]
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        assert "inappropriate" in get_labels(body)

    def test_discriminatory_language(self):
        payload = make_payload(
            current_text="People like you are such a burden. You should just be grateful someone helps you.",
            current_role="support_worker"
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        assert "inappropriate" in get_labels(body)


# ── Multi-label Classification ─────────────────────────────────────────────────

class TestMultiLabelClassification:
    def test_emergency_and_inappropriate_together(self):
        """
        Worker is being abusive AND the client is in distress —
        should return both emergency + inappropriate.
        """
        payload = make_payload(
            current_text="I don't care if you're in pain, figure it out yourself. I'm leaving.",
            current_role="support_worker",
            history=[
                {
                    "role": "client",
                    "text": "Please don't leave, I fell and I think I broke something. I need help.",
                    "timestamp": "2025-06-01T10:03:00Z"
                }
            ]
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        labels = get_labels(body)
        assert "emergency" in labels
        assert "inappropriate" in labels

        # normal should NOT be present alongside emergency/inappropriate
        assert "normal" not in labels

    def test_normal_never_mixed_with_other_labels(self):
        """Normal should only appear alone — never with emergency or inappropriate."""
        payload = make_payload(
            current_text="I've finished the morning routine. Everything went smoothly.",
            current_role="support_worker"
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        labels = get_labels(body)
        if "normal" in labels:
            assert "emergency" not in labels
            assert "inappropriate" not in labels


# ── History Trimming ───────────────────────────────────────────────────────────

class TestHistoryTrimming:
    def test_sends_more_than_limit(self):
        """Send 10 messages in history — service should still work (trims to 5 internally)."""
        history = [
            {
                "role": "client" if i % 2 == 0 else "support_worker",
                "text": f"Message number {i}",
                "timestamp": f"2025-06-01T09:0{i}:00Z"
            }
            for i in range(10)
        ]
        payload = make_payload(
            current_text="Everything is going fine today.",
            current_role="support_worker",
            history=history
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        # messages_analysed = trimmed history (5) + current (1) = 6
        assert body["messages_analysed"] == 6


# ── Validation Errors ──────────────────────────────────────────────────────────

class TestValidation:
    def test_missing_conversation_id(self):
        payload = {
            "provider_id": "org_001",
            "current_message": {
                "role": "support_worker",
                "text": "hello",
                "timestamp": "2025-06-01T10:05:00Z"
            }
        }
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 422

    def test_missing_provider_id(self):
        payload = {
            "conversation_id": "conv_001",
            "current_message": {
                "role": "support_worker",
                "text": "hello",
                "timestamp": "2025-06-01T10:05:00Z"
            }
        }
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 422

    def test_invalid_role(self):
        payload = make_payload(
            current_text="hello",
            current_role="manager"   # invalid — not support_worker or client
        )
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 422

    def test_invalid_timestamp_format(self):
        payload = {
            "conversation_id": "conv_001",
            "provider_id": "org_001",
            "current_message": {
                "role": "support_worker",
                "text": "hello",
                "timestamp": "01-06-2025"   # wrong format
            }
        }
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 422

    def test_empty_text(self):
        payload = make_payload(current_text="")
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 422

    def test_missing_current_message(self):
        payload = {
            "conversation_id": "conv_001",
            "provider_id": "org_001"
        }
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 422


# ── Response Structure ─────────────────────────────────────────────────────────

class TestResponseStructure:
    def test_all_required_fields_present(self):
        payload = make_payload(current_text="Good morning, ready to start the shift.")
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        assert "conversation_id" in body
        assert "provider_id" in body
        assert "is_uncertain" in body
        assert "classifications" in body
        assert "messages_analysed" in body
        assert "analysed_at" in body

    def test_classification_fields(self):
        payload = make_payload(current_text="Good morning, ready to start the shift.")
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()

        for c in body["classifications"]:
            assert "label" in c
            assert "confidence" in c
            assert "reason" in c
            assert_valid_classification(c)

    def test_provider_id_echoed_back(self):
        """Ensure provider_id is always returned — critical for data isolation."""
        payload = make_payload(current_text="Hello.")
        r = requests.post(f"{BASE_URL}/classify", json=payload, headers=auth_headers())
        assert r.status_code == 200
        assert r.json()["provider_id"] == "test_org_001"
