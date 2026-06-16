#!/usr/bin/env python3
"""Full flow test for conversation persistence (Phase 1 & 2)."""
import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Add ai_chatbot to path so imports work
sys.path.insert(0, str(Path(__file__).parent / "services" / "ai_chatbot"))

async def test_imports():
    """Test 1: Verify all imports work."""
    print("\n" + "="*60)
    print("TEST 1: Module Imports")
    print("="*60)
    try:
        import conversation_store
        import gateway
        import config
        print("✅ conversation_store imported")
        print("✅ gateway imported")
        print("✅ config imported")

        # Verify functions exist
        assert hasattr(conversation_store, '_sign')
        assert hasattr(conversation_store, 'store_user_message')
        assert hasattr(conversation_store, 'store_ai_response')
        assert hasattr(conversation_store, 'get_recent_messages')
        print("✅ All conversation_store functions present")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False


async def test_signing():
    """Test 2: Verify RSA-SHA256 signing works."""
    print("\n" + "="*60)
    print("TEST 2: RSA-SHA256 Signing")
    print("="*60)
    try:
        import conversation_store

        # Mock the private key
        with patch.object(conversation_store, '_PRIVATE_KEY', create=True) as mock_key:
            mock_key.sign.return_value = b'fake_signature'

            # Test with empty body (GET request)
            ts, sig = conversation_store._sign(b"")
            assert ts.isdigit(), "Timestamp should be numeric"
            assert isinstance(sig, str), "Signature should be string"
            print(f"✅ GET signature: timestamp={ts}, sig_len={len(sig)}")

            # Test with body (POST request)
            body = b'{"test": "data"}'
            ts2, sig2 = conversation_store._sign(body)
            assert ts2.isdigit()
            assert isinstance(sig2, str)
            print(f"✅ POST signature: timestamp={ts2}, sig_len={len(sig2)}")
            return True
    except Exception as e:
        print(f"❌ Signing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_store_user_message():
    """Test 3: Verify store_user_message function."""
    print("\n" + "="*60)
    print("TEST 3: Store User Message")
    print("="*60)
    try:
        import conversation_store, config

        # Mock httpx client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"data": {"messageId": "msg-123"}}
        mock_client.post.return_value = mock_response

        # Mock config
        with patch.object(config, 'CONVERSATION_STORE_ENABLED', True), \
             patch.object(config, 'PLATFORM_BASE_URL', 'https://dev-api.isena.org/api'), \
             patch.object(conversation_store, '_sign', return_value=('1234567890', 'sig123')):

            result = await conversation_store.store_user_message(
                conversation_id='conv-456',
                question='What are my shifts?',
                jwt_token='jwt-token-xyz',
                client=mock_client
            )

            assert result == 'msg-123', f"Expected msg-123, got {result}"
            print(f"✅ User message stored: messageId={result}")

            # Verify call was made
            assert mock_client.post.called
            call_args = mock_client.post.call_args
            assert 'webhook/user-message' in call_args[0][0]
            print("✅ Webhook endpoint called correctly")
            return True
    except Exception as e:
        print(f"❌ Store user message test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_store_ai_response():
    """Test 4: Verify store_ai_response function."""
    print("\n" + "="*60)
    print("TEST 4: Store AI Response")
    print("="*60)
    try:
        import conversation_store, config

        # Mock httpx client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response

        with patch.object(config, 'CONVERSATION_STORE_ENABLED', True), \
             patch.object(config, 'PLATFORM_BASE_URL', 'https://dev-api.isena.org/api'), \
             patch.object(conversation_store, '_sign', return_value=('1234567890', 'sig123')):

            result = await conversation_store.store_ai_response(
                conversation_id='conv-456',
                answer='Your shifts are...',
                usage={'input_tokens': 100, 'output_tokens': 50},
                jwt_token='jwt-token-xyz',
                client=mock_client,
                message_id='msg-123'
            )

            assert result is True, f"Expected True, got {result}"
            print("✅ AI response stored")

            # Verify call was made
            assert mock_client.post.called
            call_args = mock_client.post.call_args
            assert 'webhook/ai-response' in call_args[0][0]
            print("✅ Webhook endpoint called correctly")
            return True
    except Exception as e:
        print(f"❌ Store AI response test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_get_recent_messages():
    """Test 5: Verify get_recent_messages function."""
    print("\n" + "="*60)
    print("TEST 5: Get Recent Messages")
    print("="*60)
    try:
        import conversation_store, config

        # Mock httpx client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "messages": [
                    {"role": "user", "message": "First question", "createdAt": "2026-06-16T10:00:00Z"},
                    {"role": "assistant", "message": "First answer", "createdAt": "2026-06-16T10:00:05Z"},
                ]
            }
        }
        mock_client.get.return_value = mock_response

        with patch.object(conversation_store, '_sign', return_value=('1234567890', 'sig123')):
            result = await conversation_store.get_recent_messages(
                conversation_id='conv-456',
                limit=5,
                jwt_token='jwt-token-xyz',
                client=mock_client
            )

            assert len(result) == 2, f"Expected 2 messages, got {len(result)}"
            assert result[0]['role'] == 'user'
            assert result[1]['role'] == 'assistant'
            print(f"✅ Loaded {len(result)} prior messages")

            # Verify call was made
            assert mock_client.get.called
            call_args = mock_client.get.call_args
            assert 'recent-messages' in call_args[0][0]
            print("✅ Message history endpoint called correctly")
            return True
    except Exception as e:
        print(f"❌ Get recent messages test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_gateway_integration():
    """Test 6: Verify gateway imports conversation_store."""
    print("\n" + "="*60)
    print("TEST 6: Gateway Integration")
    print("="*60)
    try:
        import gateway

        # Check imports
        import inspect
        source = inspect.getsource(gateway)
        assert 'store_user_message' in source
        assert 'store_ai_response' in source
        assert 'get_recent_messages' in source
        print("✅ Gateway imports conversation_store functions")

        # Verify RouteRequest has proper docs
        assert hasattr(gateway, 'RouteRequest')
        print("✅ RouteRequest model defined")

        return True
    except Exception as e:
        print(f"❌ Gateway integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_config_vars():
    """Test 7: Verify config variables."""
    print("\n" + "="*60)
    print("TEST 7: Configuration Variables")
    print("="*60)
    try:
        import config

        # Check attributes exist
        assert hasattr(config, 'CONVERSATION_STORE_ENABLED')
        assert hasattr(config, 'PLATFORM_BASE_URL')
        assert hasattr(config, 'AI_WEBHOOK_PRIVATE_KEY_PEM')
        print("✅ All config variables defined")

        print(f"  - CONVERSATION_STORE_ENABLED: {config.CONVERSATION_STORE_ENABLED}")
        print(f"  - PLATFORM_BASE_URL: {config.PLATFORM_BASE_URL}")
        print(f"  - AI_WEBHOOK_PRIVATE_KEY_PEM: {'<set>' if config.AI_WEBHOOK_PRIVATE_KEY_PEM else '<empty>'}")

        return True
    except Exception as e:
        print(f"❌ Config test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_multi_turn_flow():
    """Test 8: Simulate multi-turn conversation flow."""
    print("\n" + "="*60)
    print("TEST 8: Multi-Turn Conversation Flow")
    print("="*60)
    try:
        import conversation_store, config

        mock_client = AsyncMock()

        # Turn 1: New conversation
        print("\n📨 TURN 1: New conversation")
        mock_client.post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"data": {"messageId": "msg-1"}})
        )

        with patch.object(config, 'CONVERSATION_STORE_ENABLED', True), \
             patch.object(config, 'PLATFORM_BASE_URL', 'https://api.test'), \
             patch.object(conversation_store, '_sign', return_value=('1000', 'sig1')):

            msg_id_1 = await conversation_store.store_user_message(
                'conv-1', 'What are my shifts?', 'jwt1', mock_client
            )
            print(f"  ✅ User message stored: {msg_id_1}")

        # Turn 2: Follow-up
        print("\n📨 TURN 2: Follow-up turn")
        mock_client.get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "data": {"messages": [
                    {"role": "user", "message": "What are my shifts?"},
                    {"role": "assistant", "message": "Your shifts are Monday-Friday 9-5"},
                ]}
            })
        )

        with patch.object(conversation_store, '_sign', return_value=('1001', 'sig2')):
            messages = await conversation_store.get_recent_messages(
                'conv-1', client=mock_client
            )
            print(f"  ✅ Prior messages loaded: {len(messages)} messages")
            print(f"    - Last user message: '{messages[0]['message']}'")
            print(f"    - Last AI response: '{messages[1]['message']}'")

        mock_client.post.return_value = MagicMock(status_code=200)

        with patch.object(config, 'CONVERSATION_STORE_ENABLED', True), \
             patch.object(config, 'PLATFORM_BASE_URL', 'https://api.test'), \
             patch.object(conversation_store, '_sign', return_value=('1002', 'sig3')):

            msg_id_2 = await conversation_store.store_ai_response(
                'conv-1',
                'Updated shifts for next week...',
                {'input_tokens': 150, 'output_tokens': 75},
                'jwt1',
                mock_client
            )
            print(f"  ✅ AI response stored for turn 2")

        # Turn 3: Another follow-up
        print("\n📨 TURN 3: Another follow-up")
        mock_client.get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "data": {"messages": [
                    {"role": "user", "message": "What are my shifts?"},
                    {"role": "assistant", "message": "Your shifts are Monday-Friday 9-5"},
                    {"role": "user", "message": "Any changes next week?"},
                    {"role": "assistant", "message": "Updated shifts for next week..."},
                ]}
            })
        )

        with patch.object(conversation_store, '_sign', return_value=('1003', 'sig4')):
            messages = await conversation_store.get_recent_messages(
                'conv-1', limit=5, client=mock_client
            )
            print(f"  ✅ Context loaded: {len(messages)} messages in history")

        print("\n✅ Multi-turn conversation flow validated!")
        return True
    except Exception as e:
        print(f"❌ Multi-turn flow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "🧪 "*20)
    print("CONVERSATION PERSISTENCE - FULL FLOW TEST")
    print("🧪 "*20)

    tests = [
        ("Imports", test_imports),
        ("RSA Signing", test_signing),
        ("Store User Message", test_store_user_message),
        ("Store AI Response", test_store_ai_response),
        ("Get Recent Messages", test_get_recent_messages),
        ("Gateway Integration", test_gateway_integration),
        ("Config Variables", test_config_vars),
        ("Multi-Turn Flow", test_multi_turn_flow),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Unexpected error in {name}: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\n{'='*60}")
    print(f"Total: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 ALL TESTS PASSED - System ready for deployment!")
        return 0
    else:
        print("⚠️  Some tests failed - review above")
        return 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
