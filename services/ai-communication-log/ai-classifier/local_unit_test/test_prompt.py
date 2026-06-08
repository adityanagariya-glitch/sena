"""
Layer 1 — Prompt Test
Tests the prompt builder in isolation. No AWS, no FastAPI needed.

Run:
    python tests/test_layer1_prompt.py
"""

from datetime import datetime
from app.prompts.classification_prompt import build_user_prompt, SYSTEM_PROMPT
from app.models.schemas import Message


def separator(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def test_system_prompt():
    separator("SYSTEM PROMPT")
    print(SYSTEM_PROMPT)
    assert "emergency" in SYSTEM_PROMPT.lower(), "FAIL — 'emergency' missing from system prompt"
    assert "inappropriate" in SYSTEM_PROMPT.lower(), "FAIL — 'inappropriate' missing from system prompt"
    assert "normal" in SYSTEM_PROMPT.lower(), "FAIL — 'normal' missing from system prompt"
    assert "ndis" in SYSTEM_PROMPT.lower(), "FAIL — 'ndis' missing from system prompt"
    assert "json" in SYSTEM_PROMPT.lower(), "FAIL — JSON instruction missing from system prompt"
    print("\n System prompt looks correct")


def test_user_prompt_no_history():
    separator("USER PROMPT — No History (first message)")
    current = Message(
        role="support_worker",
        text="Good morning! How are you feeling today?",
        timestamp=datetime(2025, 6, 1, 10, 5, 0)
    )
    prompt = build_user_prompt(current, history=[])
    print(prompt)

    assert "CURRENT MESSAGE" in prompt, "FAIL — current message section missing"
    assert "CONVERSATION HISTORY" not in prompt, "FAIL — history section should not appear when empty"
    assert "Good morning" in prompt, "FAIL — current message text missing"
    assert "SUPPORT WORKER" in prompt, "FAIL — role missing"
    print("\n No-history prompt looks correct")


def test_user_prompt_with_history():
    separator("USER PROMPT — With History")
    current = Message(
        role="support_worker",
        text="I don't want to deal with you anymore.",
        timestamp=datetime(2025, 6, 1, 10, 5, 0)
    )
    history = [
        Message(
            role="client",
            text="I need help getting to the bathroom.",
            timestamp=datetime(2025, 6, 1, 10, 3, 0)
        ),
        Message(
            role="support_worker",
            text="Wait, I'm busy.",
            timestamp=datetime(2025, 6, 1, 10, 4, 0)
        )
    ]
    prompt = build_user_prompt(current, history=history)
    print(prompt)

    assert "CONVERSATION HISTORY" in prompt, "FAIL — history section missing"
    assert "CURRENT MESSAGE" in prompt, "FAIL — current message section missing"
    assert "I need help getting to the bathroom" in prompt, "FAIL — history message 1 missing"
    assert "Wait, I'm busy" in prompt, "FAIL — history message 2 missing"
    assert "I don't want to deal with you" in prompt, "FAIL — current message missing"

    # Check ordering — history should appear before current message
    history_pos = prompt.index("CONVERSATION HISTORY")
    current_pos = prompt.index("CURRENT MESSAGE")
    assert history_pos < current_pos, "FAIL — history should appear before current message"

    print("\n History prompt looks correct — ordering is oldest → newest → current")


def test_user_prompt_roles():
    separator("USER PROMPT — Role Formatting")
    current = Message(
        role="client",
        text="I feel very dizzy.",
        timestamp=datetime(2025, 6, 1, 10, 5, 0)
    )
    history = [
        Message(
            role="support_worker",
            text="How are you feeling?",
            timestamp=datetime(2025, 6, 1, 10, 3, 0)
        )
    ]
    prompt = build_user_prompt(current, history=history)
    print(prompt)

    assert "SUPPORT WORKER" in prompt, "FAIL — support_worker role not formatted correctly"
    assert "CLIENT" in prompt, "FAIL — client role not formatted correctly"
    assert "support_worker" not in prompt, "FAIL — raw role value should not appear, should be formatted"
    print("\n Roles formatted correctly")


def test_timestamp_format():
    separator("USER PROMPT — Timestamp Format")
    current = Message(
        role="support_worker",
        text="Test message",
        timestamp=datetime(2025, 6, 1, 10, 5, 0)
    )
    prompt = build_user_prompt(current, history=[])
    print(prompt)

    assert "2025-06-01" in prompt, "FAIL — date not in prompt"
    assert "10:05:00 UTC" in prompt, "FAIL — time not in prompt"
    print("\n Timestamp formatted correctly")


if __name__ == "__main__":
    print("\n🔍 LAYER 1 — PROMPT TESTS\n")
    print("No AWS credentials needed. No server needed.\n")

    try:
        test_system_prompt()
        test_user_prompt_no_history()
        test_user_prompt_with_history()
        test_user_prompt_roles()
        test_timestamp_format()

        print("\n" + "=" * 60)
        print("ALL PROMPT TESTS PASSED")
        print("=" * 60)
        print("\nNext step → run: python tests/test_layer2_bedrock.py\n")

    except AssertionError as e:
        print(f"\n TEST FAILED: {e}\n")
        raise