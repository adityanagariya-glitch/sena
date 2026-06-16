"""Platform conversation persistence — async, fail-soft storage via webhooks.

Stores user messages and AI responses to the platform's conversation API before
they're returned to the frontend. All operations are fire-and-forget (non-blocking)
and log errors instead of raising them into the SSE stream.
"""
import asyncio
import base64
import json
import logging
import time
from typing import Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

import config

logger = logging.getLogger(__name__)

# Load private key at import time.
# Normalize escaped newlines: docker-compose `env_file` passes "\n" as literal
# backslash-n, but load_pem_private_key needs real newlines. This handles both
# the Docker case (literal \n) and the local .env case (already real newlines).
_PRIVATE_KEY = None
if config.AI_WEBHOOK_PRIVATE_KEY_PEM:
    _pem = config.AI_WEBHOOK_PRIVATE_KEY_PEM.replace("\\n", "\n").strip()
    try:
        _PRIVATE_KEY = serialization.load_pem_private_key(
            _pem.encode(),
            password=None,
        )
    except Exception as e:
        logger.error(f"Failed to load AI_WEBHOOK_PRIVATE_KEY_PEM: {e}")


def _sign(raw_body: bytes) -> tuple[str, str]:
    """Sign a request body with RSA-SHA256.

    Returns: (timestamp, base64-encoded signature)
    """
    if not _PRIVATE_KEY:
        raise RuntimeError("Private key not loaded — check AI_WEBHOOK_PRIVATE_KEY_PEM")

    ts = str(int(time.time()))
    message = f"{ts}.".encode() + raw_body
    sig = _PRIVATE_KEY.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return ts, base64.b64encode(sig).decode()


async def store_user_message(
    conversation_id: str,
    question: str,
    jwt_token: str,
    client: httpx.AsyncClient,
) -> Optional[str]:
    """Store a user message to the platform conversation API.

    Returns: message_id if successful, None on error (logged but not raised).
    """
    if not config.CONVERSATION_STORE_ENABLED or not conversation_id:
        return None

    try:
        url = f"{config.PLATFORM_BASE_URL}/ai-chat/webhook/user-message"
        body = json.dumps({
            "conversationId": conversation_id,
            "message": question,
            "role": "user",
        })
        raw_body = body.encode()

        ts, sig = _sign(raw_body)

        response = await client.post(
            url,
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}",
                "X-AI-Timestamp": ts,
                "X-AI-Signature": sig,
            },
            timeout=5.0,
        )

        if response.status_code not in (200, 201):
            logger.warning(
                f"Failed to store user message: {response.status_code} {response.text}"
            )
            return None

        data = response.json()
        message_id = data.get("data", {}).get("messageId")
        logger.debug(f"Stored user message {message_id} to conversation {conversation_id}")
        return message_id

    except Exception as e:
        logger.exception(f"Error storing user message for {conversation_id}: {e}")
        return None


async def store_ai_response(
    conversation_id: str,
    answer: str,
    usage: dict,
    jwt_token: str,
    client: httpx.AsyncClient,
    message_id: Optional[str] = None,
) -> bool:
    """Store an AI response to the platform conversation API.

    Returns: True if successful, False on error (logged but not raised).
    """
    if not config.CONVERSATION_STORE_ENABLED or not conversation_id:
        return False

    try:
        url = f"{config.PLATFORM_BASE_URL}/ai-chat/webhook/ai-response"
        body = json.dumps({
            "conversationId": conversation_id,
            "message": answer,
            "role": "assistant",
            "usage": usage,
            "messageId": message_id,
            "status": "completed",
        })
        raw_body = body.encode()

        ts, sig = _sign(raw_body)

        response = await client.post(
            url,
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}",
                "X-AI-Timestamp": ts,
                "X-AI-Signature": sig,
            },
            timeout=5.0,
        )

        if response.status_code not in (200, 201):
            logger.warning(
                f"Failed to store AI response: {response.status_code} {response.text}"
            )
            return False

        logger.debug(f"Stored AI response to conversation {conversation_id}")
        return True

    except Exception as e:
        logger.exception(f"Error storing AI response for {conversation_id}: {e}")
        return False


async def get_recent_messages(
    conversation_id: str,
    limit: int = 5,
    message_id: Optional[str] = None,
    jwt_token: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> list:
    """Load recent messages from a conversation for context injection.

    Returns: list of prior messages (role, message, createdAt), or empty list on error.
    """
    if not conversation_id or not client:
        return []

    try:
        url = f"{config.PLATFORM_BASE_URL}/ai-chat/conversations/{conversation_id}/recent-messages"
        params = {"limit": min(limit, 50)}
        if message_id:
            params["messageId"] = message_id

        headers = {}
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"

        ts, sig = _sign(b"")
        headers["X-AI-Timestamp"] = ts
        headers["X-AI-Signature"] = sig

        response = await client.get(url, params=params, headers=headers, timeout=5.0)

        if response.status_code != 200:
            logger.warning(f"Failed to load messages: {response.status_code}")
            return []

        data = response.json()
        messages = data.get("data", {}).get("messages", [])
        logger.debug(f"Loaded {len(messages)} prior messages for {conversation_id}")
        return messages

    except Exception as e:
        logger.exception(f"Error loading recent messages for {conversation_id}: {e}")
        return []
