"""Tests for the OCR service scaffold."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from ocr.main import create_app


@pytest.fixture
def app():
    """Create a test app instance."""
    return create_app()


@pytest.fixture
async def client(app) -> AsyncClient:
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_check_returns_200(client: AsyncClient) -> None:
    """Health check endpoint should respond without tenant context."""
    response = await client.get("/v1/ocr/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "sena-ocr"
    assert data["status"] in ("healthy", "unhealthy")


@pytest.mark.asyncio
async def test_extract_rejects_without_tenant_id(client: AsyncClient) -> None:
    """OCR extract endpoint should reject requests without tenant ID."""
    response = await client.post(
        "/v1/ocr/extract",
        data={"document_type": "drivers_licence"},
        files={"file": ("test.jpg", b"fake-image-data", "image/jpeg")},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["status"] == "error"
    assert data["error"]["code"] == "TENANT_RESOLUTION_FAILED"


@pytest.mark.asyncio
async def test_extract_with_tenant_returns_501_scaffold(client: AsyncClient) -> None:
    """OCR extract with valid tenant should return 501 (not implemented yet)."""
    response = await client.post(
        "/v1/ocr/extract",
        data={"document_type": "drivers_licence"},
        files={"file": ("test.jpg", b"fake-image-data", "image/jpeg")},
        headers={
            "X-Tenant-ID": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "X-User-ID": "test-user",
            "X-User-Role": "admin",
        },
    )
    assert response.status_code == 501
    data = response.json()
    assert data["error"]["code"] == "NOT_IMPLEMENTED"
    assert data["metadata"]["tenant_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
