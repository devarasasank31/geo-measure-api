"""Global error handling, logging and HTTP-level failure tests."""

from __future__ import annotations

import logging
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db import repository


@pytest.fixture()
def error_client(app_settings: Settings) -> TestClient:
    """Client that returns 500 responses instead of re-raising them."""
    from app.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def test_unhandled_exception_returns_structured_500(
    error_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(file_id: str):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(repository, "get_record", boom)

    response = error_client.get("/api/files/abc123/")

    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "INTERNAL_ERROR"
    assert "Traceback" not in body["message"]
    assert "database exploded" not in body["message"]


def test_method_not_allowed_returns_structured_error(client: TestClient) -> None:
    response = client.get("/api/files/")

    assert response.status_code == 405
    error = response.json()["error"]
    assert error["code"] == "METHOD_NOT_ALLOWED"
    assert "Traceback" not in error["message"]


def test_validation_error_reports_field_context(client: TestClient) -> None:
    response = client.post("/api/files/")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "file" in error["message"]


def test_request_logging_records_method_path_and_status(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.main")

    client.get("/health")

    messages = [record.getMessage() for record in caplog.records]
    assert any("GET /health -> 200" in message for message in messages)


def test_error_and_success_responses_never_leak_internals(
    client: TestClient, upload_bytes: Callable
) -> None:
    responses = [
        client.get("/api/files/missing/"),
        client.get("/api/nope/"),
        upload_bytes(b"not a geospatial file", "notes.txt"),
    ]

    for response in responses:
        text = response.text
        for leak in ("Traceback", "File \"", ".py", "site-packages"):
            assert leak not in text
