import os
import pytest
from fastapi.testclient import TestClient
from voice.main import create_app

os.environ.setdefault("SENA_AI_AI_DB_URL", "sqlite+aiosqlite:///./test_ai.db")
os.environ.setdefault("SENA_AI_SHARED_DB_URL", "sqlite+aiosqlite:///./test_shared.db")
os.environ.setdefault("SENA_AI_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("SENA_AI_LIVEKIT_API_KEY", "devkey")
os.environ.setdefault("SENA_AI_LIVEKIT_API_SECRET", "devsecret")
os.environ.setdefault("SENA_AI_LIVEKIT_URL", "wss://livekit.local")
os.environ.setdefault(
    "SENA_AI_SNS_CASE_NOTE_TOPIC_ARN", "arn:aws:sns:ap-southeast-2:111111111111:case-note-events"
)


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def dev_headers():
    return {
        "X-Tenant-ID": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "X-User-ID": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "X-User-Role": "support_worker",
        "X-Staff-ID": "cccccccc-cccc-cccc-cccc-cccccccccccc",
    }


@pytest.fixture
def manager_headers():
    return {
        "X-Tenant-ID": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "X-User-ID": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "X-User-Role": "manager",
        "X-Staff-ID": "dddddddd-dddd-dddd-dddd-dddddddddddd",
    }
