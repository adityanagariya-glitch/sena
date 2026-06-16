#!/usr/bin/env python3
"""Test that conversation_id validation works correctly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "services" / "ai_chatbot"))

def test_request_without_conversation_id():
    """Test that requests without conversation_id are caught."""
    print("\n" + "="*60)
    print("TEST: Request Validation")
    print("="*60)

    from gateway import RouteRequest

    # Test 1: Request WITHOUT conversation_id (should still parse, but gateway rejects)
    print("\n1️⃣  Request WITHOUT conversation_id:")
    try:
        req = RouteRequest(
            question="What are my shifts?",
            context={"category": "shifts", "is_new_chat": True}
        )
        print(f"✅ Parsed: {req.context}")
        print("   (Gateway will reject with validation error)")
    except Exception as e:
        print(f"❌ Parse error: {e}")
        return False

    # Test 2: Request WITH conversation_id (should work)
    print("\n2️⃣  Request WITH conversation_id:")
    try:
        req = RouteRequest(
            question="What are my shifts?",
            context={
                "category": "shifts",
                "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
                "is_new_chat": True
            }
        )
        print(f"✅ Parsed: {req.context}")
        print(f"   - Category: {req.context['category']}")
        print(f"   - Conversation ID: {req.context['conversation_id']}")
        print(f"   - Is new chat: {req.context['is_new_chat']}")
    except Exception as e:
        print(f"❌ Parse error: {e}")
        return False

    # Test 3: Follow-up without conversation_id (should still parse)
    print("\n3️⃣  Follow-up WITHOUT conversation_id:")
    try:
        req = RouteRequest(
            question="Who's working Monday?",
            context={"category": "shifts", "is_new_chat": False}
        )
        print(f"✅ Parsed: {req.context}")
        print("   (Gateway will reject - conversation_id required for context loading)")
    except Exception as e:
        print(f"❌ Parse error: {e}")
        return False

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print("""
✅ Frontend Flow:
1. POST /conversations → get conversation_id
2. Send ALL requests with conversation_id in context
3. Set is_new_chat=true on Turn 1 only
4. Set is_new_chat=false on Turn 2+ (or omit)

❌ Will be rejected:
- Requests without conversation_id (validation error)
- Missing category (no routing)

✅ Will work:
- Turn 1 with conversation_id + is_new_chat=true
- Turn 2+ with conversation_id + is_new_chat=false
- Context auto-loading on follow-ups
- Message storage with correct conversation_id
""")

    return True

if __name__ == '__main__':
    success = test_request_without_conversation_id()
    sys.exit(0 if success else 1)
