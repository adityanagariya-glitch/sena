from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import structlog

log = structlog.get_logger(__name__)


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """HMAC-SHA256 hex signature. Returns empty string when no secret configured."""
    if not secret:
        return ""
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


async def fire_webhook(
    url: str,
    event: str,
    payload: dict,
    secret: str = "",
    max_retries: int = 3,
) -> bool:
    """
    POST payload to url with retry.
    Returns True if any attempt succeeded (2xx), False after all retries exhausted.
    """
    body = json.dumps(payload, default=str).encode()
    signature = _sign_payload(body, secret)

    headers = {
        "Content-Type": "application/json",
        "X-SENA-AI-Event": event,
        "X-SENA-AI-Signature": signature,
        "X-SENA-AI-Timestamp": datetime.now(timezone.utc).isoformat(),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(max_retries):
            try:
                resp = await client.post(url, content=body, headers=headers)
                if resp.is_success:
                    log.info(
                        "webhook_delivered",
                        url=url,
                        webhook_event=event,
                        attempt=attempt,
                        status=resp.status_code,
                    )
                    return True
                log.warning(
                    "webhook_bad_status",
                    url=url,
                    webhook_event=event,
                    attempt=attempt,
                    status=resp.status_code,
                )
            except Exception as exc:
                log.warning(
                    "webhook_error",
                    url=url,
                    webhook_event=event,
                    attempt=attempt,
                    error=str(exc),
                )

            if attempt < max_retries - 1:
                wait = 4**attempt  # 1s, 4s, 16s
                await asyncio.sleep(wait)

    log.error("webhook_failed_all_retries", url=url, webhook_event=event, max_retries=max_retries)
    return False
