"""Health endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_validated_against_response_model(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json()["status"], str)


def test_openapi_documentation_is_available(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["info"]["title"] == "GeoMeasure API"
    assert "/health" in payload["paths"]
