"""Fire-and-forget webhook to notify platform backend of restrictive practice results."""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from case_review.core.settings import settings
from case_review.models.schemas import PipelineResult

logger = logging.getLogger(__name__)


async def fire_webhook(result: PipelineResult) -> None:
    """POST pipeline result to rp_webhook_url. No-op if URL not configured.

    Fires for every completed run, not only alerts — caller decides whether
    to call based on alert_required or unconditionally.
    Signs the body with HMAC-SHA256 if rp_webhook_secret is set.
    Failures are logged and swallowed — webhook must not break the pipeline response.
    """
    if not settings.rp_webhook_url:
        return

    payload = {
        "event": "restrictive_practice_evaluated",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "case_note_id": str(result.case_note_id),
        "client_id": result.client_id,
        "alert_required": result.alert_required,
        "triage_flagged": result.triage.flagged,
        "authorisation_status": (
            result.cross_check.authorisation_status.value if result.cross_check else None
        ),
        "practice_category": (
            result.evaluator.practice_category if result.evaluator else None
        ),
        "policy_violation_risk": (
            result.evaluator.policy_violation_risk.value if result.evaluator else None
        ),
    }

    body = json.dumps(payload, separators=(",", ":"))
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if settings.rp_webhook_secret:
        sig = hmac.new(
            settings.rp_webhook_secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()
        headers["X-Signature-SHA256"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.rp_webhook_url, content=body, headers=headers)
            resp.raise_for_status()
            logger.info(
                "webhook ok case_note_id=%s status=%d",
                result.case_note_id,
                resp.status_code,
            )
    except Exception as exc:
        logger.warning(
            "webhook failed case_note_id=%s url=%s error=%s",
            result.case_note_id,
            settings.rp_webhook_url,
            exc,
        )
