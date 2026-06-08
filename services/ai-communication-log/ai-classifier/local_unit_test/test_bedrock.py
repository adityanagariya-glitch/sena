"""
Layer 2 — Bedrock Test
Tests BedrockService directly. No FastAPI needed.
Requires AWS credentials configured in .env or environment.

Run:
    python tests/test_layer2_bedrock.py
"""

from datetime import datetime
from app.services.bedrock_service import BedrockService
from app.models.schemas import Message
from app.core.config import settings


def separator(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def print_results(results):
    for r in results:
        print(f"  Label      : {r.label}")
        print(f"  Confidence : {r.confidence}")
        print(f"  Reason     : {r.reason}")
        print("  ---")


def assert_valid_results(results, expected_labels=None):
    assert len(results) > 0, "FAIL — no classifications returned"
    for r in results:
        assert r.label in settings.VALID_LABELS, f"FAIL — invalid label: {r.label}"
        assert 0.0 <= r.confidence <= 1.0, f"FAIL — confidence out of range: {r.confidence}"
        assert isinstance(r.reason, str) and len(r.reason) > 0, "FAIL — reason is empty"

    if expected_labels:
        actual_labels = [r.label for r in results]
        for label in expected_labels:
            assert label in actual_labels, f"FAIL — expected label '{label}' not in {actual_labels}"


def test_bedrock_connection():
    separator("BEDROCK CONNECTION")
    print(f"  Region : {settings.AWS_REGION}")
    print(f"  Model  : {settings.BEDROCK_MODEL_ID}")
    print("\n  Sending test message to Bedrock...")

    bedrock = BedrockService()
    current = Message(
        role="support_worker",
        text="Good morning! How are you feeling today?",
        timestamp=datetime.utcnow()
    )
    results = bedrock.classify(current_message=current, history=[])
    print_results(results)

    assert_valid_results(results)
    print(" Bedrock connection working")


def test_normal_classification():
    separator("BEDROCK — Normal Classification")
    bedrock = BedrockService()
    current = Message(
        role="support_worker",
        text="I've completed the morning routine. Everything went smoothly today.",
        timestamp=datetime.utcnow()
    )
    results = bedrock.classify(current_message=current, history=[])
    print_results(results)

    assert_valid_results(results, expected_labels=["normal"])
    labels = [r.label for r in results]
    assert "emergency" not in labels, "FAIL — normal message flagged as emergency"
    assert "inappropriate" not in labels, "FAIL — normal message flagged as inappropriate"
    print(" Normal classification correct")


def test_emergency_classification():
    separator("BEDROCK — Emergency Classification")
    bedrock = BedrockService()
    current = Message(
        role="client",
        text="I don't want to live anymore. I've been thinking about hurting myself.",
        timestamp=datetime.utcnow()
    )
    results = bedrock.classify(current_message=current, history=[])
    print_results(results)

    assert_valid_results(results, expected_labels=["emergency"])
    print(" Emergency classification correct")


def test_inappropriate_classification():
    separator("BEDROCK — Inappropriate Classification")
    bedrock = BedrockService()

    history = [
        Message(
            role="client",
            text="I need help getting to the bathroom.",
            timestamp=datetime.utcnow()
        )
    ]
    current = Message(
        role="support_worker",
        text="I don't want to deal with you anymore. Just do what I say and stop complaining.",
        timestamp=datetime.utcnow()
    )
    results = bedrock.classify(current_message=current, history=history)
    print_results(results)

    assert_valid_results(results, expected_labels=["inappropriate"])
    print(" Inappropriate classification correct")


def test_multilabel_classification():
    separator("BEDROCK — Multi-label (Emergency + Inappropriate)")
    bedrock = BedrockService()

    history = [
        Message(
            role="client",
            text="Please don't leave, I fell and I think I broke something. I need help.",
            timestamp=datetime.utcnow()
        )
    ]
    current = Message(
        role="support_worker",
        text="I don't care if you're in pain, figure it out yourself. I'm leaving.",
        timestamp=datetime.utcnow()
    )
    results = bedrock.classify(current_message=current, history=history)
    print_results(results)

    assert_valid_results(results, expected_labels=["emergency", "inappropriate"])

    labels = [r.label for r in results]
    assert "normal" not in labels, "FAIL — normal should not appear with emergency/inappropriate"
    print(" Multi-label classification correct")


def test_context_from_history():
    separator("BEDROCK — Context From History Matters")
    print("  Sending urgent history with silence trigger message...")
    bedrock = BedrockService()

    history = [
        Message(
            role="client",
            text="I feel very dizzy and I think I'm going to faint.",
            timestamp=datetime.utcnow()
        )
    ]
    current = Message(
        role="support_worker",
        text="SYSTEM: Support worker has not responded for 5 minutes.",
        timestamp=datetime.utcnow()
    )
    results = bedrock.classify(current_message=current, history=history)
    print_results(results)

    assert_valid_results(results)
    labels = [r.label for r in results]
    print(f"  Labels returned: {labels}")
    print("  (expecting emergency given urgent history context)")
    print("History context test complete — check labels above match expectation")


def test_response_parsing():
    separator("BEDROCK — Response Parsing (JSON structure)")
    bedrock = BedrockService()
    current = Message(
        role="support_worker",
        text="Good morning.",
        timestamp=datetime.utcnow()
    )
    results = bedrock.classify(current_message=current, history=[])

    for r in results:
        assert hasattr(r, "label"), "FAIL — label field missing"
        assert hasattr(r, "confidence"), "FAIL — confidence field missing"
        assert hasattr(r, "reason"), "FAIL — reason field missing"
        assert isinstance(r.confidence, float), "FAIL — confidence should be float"
        assert isinstance(r.reason, str), "FAIL — reason should be string"

    print_results(results)
    print(" Response parsed correctly into ClassificationResult objects")


if __name__ == "__main__":
    print("\n LAYER 2 — BEDROCK TESTS\n")
    print("AWS credentials required. No server needed.\n")

    try:
        test_bedrock_connection()
        test_normal_classification()
        test_emergency_classification()
        test_inappropriate_classification()
        test_multilabel_classification()
        test_context_from_history()
        test_response_parsing()

        print("\n" + "=" * 60)
        print("   ALL BEDROCK TESTS PASSED")
        print("=" * 60)
        print("\nNext step → start server then run: python tests/test_layer3_api.py\n")

    except AssertionError as e:
        print(f"\n TEST FAILED: {e}\n")
        raise
    except Exception as e:
        print(f"\n UNEXPECTED ERROR: {e}")
        print("\nCheck:")
        print("  - AWS credentials configured in .env")
        print("  - Bedrock model access enabled in AWS console")
        print(f"  - Region is correct: {settings.AWS_REGION}\n")
        raise