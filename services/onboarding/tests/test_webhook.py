"""Tests for webhook retry logic."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sena_common.voice.webhook import fire_webhook


class TestFireWebhook:
    async def test_success_on_first_attempt(self):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200

        with patch("sena_common.voice.webhook.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = False
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            result = await fire_webhook("http://example.com/hook", "test.event", {"k": "v"})

        assert result is True
        assert mock_client.post.call_count == 1

    async def test_retries_on_failure_then_succeeds(self):
        fail_resp = MagicMock()
        fail_resp.is_success = False
        fail_resp.status_code = 500

        ok_resp = MagicMock()
        ok_resp.is_success = True
        ok_resp.status_code = 200

        with patch("sena_common.voice.webhook.httpx.AsyncClient") as mock_cls:
            with patch("sena_common.voice.webhook.asyncio.sleep", new_callable=AsyncMock):
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = False
                mock_client.post = AsyncMock(side_effect=[fail_resp, ok_resp])
                mock_cls.return_value = mock_client

                result = await fire_webhook(
                    "http://example.com/hook", "test.event", {}, max_retries=3
                )

        assert result is True
        assert mock_client.post.call_count == 2

    async def test_returns_false_after_all_retries(self):
        fail_resp = MagicMock()
        fail_resp.is_success = False
        fail_resp.status_code = 503

        with patch("sena_common.voice.webhook.httpx.AsyncClient") as mock_cls:
            with patch("sena_common.voice.webhook.asyncio.sleep", new_callable=AsyncMock):
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = False
                mock_client.post = AsyncMock(return_value=fail_resp)
                mock_cls.return_value = mock_client

                result = await fire_webhook(
                    "http://example.com/hook", "test.event", {}, max_retries=3
                )

        assert result is False
        assert mock_client.post.call_count == 3

    async def test_handles_connection_error(self):
        with patch("sena_common.voice.webhook.httpx.AsyncClient") as mock_cls:
            with patch("sena_common.voice.webhook.asyncio.sleep", new_callable=AsyncMock):
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = False
                mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
                mock_cls.return_value = mock_client

                result = await fire_webhook(
                    "http://example.com/hook", "test.event", {}, max_retries=2
                )

        assert result is False
