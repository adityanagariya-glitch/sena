"""
Test suite for the Summary Consolidation API.

Run:
    pytest tests.py -v

Environment:
    Tests use a dedicated .env.test file or fall back to env vars.
    AWS credentials are never called — Bedrock is fully mocked.
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch
from io import BytesIO

# ── Point to a test env before any app imports ───────────────────────────────
os.environ.setdefault("API_KEY", "test-secret-key")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "fake-key-id")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "fake-secret")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("MIN_SUMMARIES", "1")
os.environ.setdefault("MAX_SUMMARIES", "10")
os.environ.setdefault("MIN_SUMMARY_LENGTH", "1")
os.environ.setdefault("MAX_SUMMARY_LENGTH", "5000")

from fastapi.testclient import TestClient
from config import get_settings

# Clear LRU cache so tests pick up os.environ overrides
get_settings.cache_clear()

from main import app  # noqa: E402  (must come after env setup)

client = TestClient(app, raise_server_exceptions=False)

VALID_HEADERS = {"X-API-Key": "test-secret-key"}
VALID_SUMMARIES = [
    "The quarterly revenue increased by 15% driven by strong product sales.",
    "Customer satisfaction scores improved following the new support initiative.",
    "Engineering shipped three major features ahead of schedule.",
    "Marketing campaigns yielded a 20% increase in lead generation.",
    "Operational costs were reduced by 8% through process automation.",
]
MOCK_CONSOLIDATED = "Overall, the company had a strong quarter with revenue growth, improved customer satisfaction, early feature delivery, better lead generation, and reduced operational costs."


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mock_bedrock_response(text: str, input_tokens: int = 100, output_tokens: int = 50) -> MagicMock:
    """Build a mock boto3 invoke_model response with Claude's message format."""
    body_content = json.dumps({
        "content": [{"text": text}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }).encode()
    mock_response = MagicMock()
    mock_response.__getitem__ = lambda self, key: BytesIO(body_content) if key == "body" else None
    return mock_response


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_check_returns_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_check_no_auth_required(self):
        """Health endpoint must be publicly accessible."""
        resp = client.get("/health")
        assert resp.status_code == 200


# ── Authentication ────────────────────────────────────────────────────────────

class TestAuth:
    def test_missing_api_key_returns_401(self):
        resp = client.post("/summarize", json={"summaries": VALID_SUMMARIES})
        assert resp.status_code == 401
        assert "Missing" in resp.json()["detail"]

    def test_wrong_api_key_returns_401(self):
        resp = client.post(
            "/summarize",
            json={"summaries": VALID_SUMMARIES},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_empty_api_key_returns_401(self):
        resp = client.post(
            "/summarize",
            json={"summaries": VALID_SUMMARIES},
            headers={"X-API-Key": ""},
        )
        assert resp.status_code == 401


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidation:
    def test_too_few_summaries_returns_422(self):
        resp = client.post(
            "/summarize",
            json={"summaries": []},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 422

    def test_too_many_summaries_returns_422(self):
        resp = client.post(
            "/summarize",
            json={"summaries": ["summary"] * 11},  # MAX is 10 in test env
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 422

    def test_empty_string_summary_returns_422(self):
        resp = client.post(
            "/summarize",
            json={"summaries": ["Valid summary.", "", "Another valid summary."]},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 422

    def test_whitespace_only_summary_returns_422(self):
        resp = client.post(
            "/summarize",
            json={"summaries": ["Valid summary.", "   ", "Another valid summary."]},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 422

    def test_missing_summaries_field_returns_422(self):
        resp = client.post(
            "/summarize",
            json={"wrong_field": ["a", "b"]},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 422

    def test_summaries_not_list_returns_422(self):
        resp = client.post(
            "/summarize",
            json={"summaries": "just a string"},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 422

    def test_summary_exceeds_max_length_returns_422(self):
        long_summary = "x" * 5001  # MAX_SUMMARY_LENGTH is 5000
        resp = client.post(
            "/summarize",
            json={"summaries": [long_summary]},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 422


# ── Happy Path ────────────────────────────────────────────────────────────────

class TestSummarize:
    @patch("bedrock._get_bedrock_client")
    def test_successful_consolidation(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_bedrock_response(MOCK_CONSOLIDATED)
        mock_client_factory.return_value = mock_client

        resp = client.post(
            "/summarize",
            json={"summaries": VALID_SUMMARIES},
            headers=VALID_HEADERS,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "consolidated_summary" in data
        assert data["consolidated_summary"] == MOCK_CONSOLIDATED
        assert data["token_usage"]["input_tokens"] == 100
        assert data["token_usage"]["output_tokens"] == 50
        assert data["token_usage"]["total_tokens"] == 150
        print("\n--- token_usage response ---")
        print(data["token_usage"])

    @patch("bedrock._get_bedrock_client")
    def test_single_summary_is_accepted(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_bedrock_response("Single summary.")
        mock_client_factory.return_value = mock_client

        resp = client.post(
            "/summarize",
            json={"summaries": ["Only one summary here."]},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 200

    @patch("bedrock._get_bedrock_client")
    def test_bedrock_client_error_returns_502(self, mock_client_factory):
        from botocore.exceptions import ClientError
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "InvokeModel",
        )
        mock_client_factory.return_value = mock_client

        resp = client.post(
            "/summarize",
            json={"summaries": VALID_SUMMARIES},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 502
        assert "ThrottlingException" in resp.json()["detail"]

    @patch("bedrock._get_bedrock_client")
    def test_malformed_bedrock_response_returns_502(self, mock_client_factory):
        mock_client = MagicMock()
        # Return a response missing the expected 'content' key
        bad_body = json.dumps({"unexpected_key": "value"}).encode()
        mock_response = MagicMock()
        mock_response.__getitem__ = lambda self, key: BytesIO(bad_body) if key == "body" else None
        mock_client.invoke_model.return_value = mock_response
        mock_client_factory.return_value = mock_client

        resp = client.post(
            "/summarize",
            json={"summaries": VALID_SUMMARIES},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 502


# ── Prompts ───────────────────────────────────────────────────────────────────

class TestPromptBuilder:
    def test_user_message_contains_all_summaries(self):
        from prompts import build_messages
        summaries = ["Alpha summary.", "Beta summary.", "Gamma summary."]
        messages = build_messages(summaries)
        user_content = messages[0]["content"]
        for s in summaries:
            assert s in user_content

    def test_user_message_contains_correct_count(self):
        from prompts import build_messages
        summaries = ["A", "B", "C"]
        messages = build_messages(summaries)
        assert "3" in messages[0]["content"]

    def test_user_message_labels_each_summary(self):
        from prompts import build_messages
        summaries = ["First.", "Second."]
        messages = build_messages(summaries)
        content = messages[0]["content"]
        assert "[Summary 1]" in content
        assert "[Summary 2]" in content

    def test_messages_has_user_role(self):
        from prompts import build_messages
        messages = build_messages(["Any summary."])
        assert messages[0]["role"] == "user"

    def test_system_prompt_is_non_empty(self):
        from prompts import get_system_prompt
        system = get_system_prompt()
        assert isinstance(system, str) and len(system) > 50

    def test_system_prompt_instructs_no_extra_content(self):
        from prompts import get_system_prompt
        system = get_system_prompt()
        # System prompt must tell Claude not to introduce new information
        assert "not present" in system or "do not introduce" in system.lower()


# ── Config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_settings_loaded_correctly(self):
        settings = get_settings()
        assert settings.api_key == "test-secret-key"
        assert settings.min_summaries == 1
        assert settings.max_summaries == 10

    def test_is_production_false_in_test_env(self):
        settings = get_settings()
        assert not settings.is_production