from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
import boto3
from voice.core.settings import settings


class EventService:
    def __init__(self):
        self.sns = boto3.client("sns", region_name=settings.aws_region)

    def build_case_note_submitted_event(
        self, tenant_id: str, case_note_id: str, summary: str, version: int = 1
    ) -> dict:
        event_id = str(uuid.uuid4())
        return {
            "id": event_id,
            "event_type": "case_note.submitted",
            "tenant_id": tenant_id,
            "version": version,
            "idempotency_key": f"{case_note_id}:{version}",
            "metadata": {
                "request_id": event_id,
                "traceparent": "",
                "hop_count": 0,
                "retry_count": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "payload": {
                "case_note_id": case_note_id,
                "summary": summary[:600],
            },
        }

    def publish_case_note_event(self, event_payload: dict) -> str:
        self.sns.publish(
            TopicArn=settings.sns_case_note_topic_arn,
            Message=json.dumps(event_payload),
            MessageAttributes={
                "event_type": {"DataType": "String", "StringValue": "case_note.submitted"},
                "tenant_id": {"DataType": "String", "StringValue": event_payload["tenant_id"]},
            },
        )
        return event_payload["id"]
