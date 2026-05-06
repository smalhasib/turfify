"""Integration tests for the /v1/health endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
async def test_health_returns_ok(api_client: AsyncClient) -> None:
    response = await api_client.get("/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["checks"]["db"] == "ok"
    assert data["checks"]["redis"] == "ok"
    assert "version" in data["checks"]


@pytest.mark.integration
async def test_root_endpoint(api_client: AsyncClient) -> None:
    response = await api_client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "turfify"
    assert "docs" in data
