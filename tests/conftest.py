"""Shared pytest fixtures.

Every test gets an isolated upload directory and SQLite database, so tests
never touch real application data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def app_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Return application settings redirected to a temporary directory."""
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "geomeasure_test.db")
    return settings


@pytest.fixture()
def client(app_settings: Settings) -> TestClient:
    """FastAPI test client bound to a freshly created application."""
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture()
def sample_kml(fixtures_dir: Path) -> Path:
    """Path to the committed multi-geometry sample KML."""
    return fixtures_dir / "sample.kml"


@pytest.fixture()
def upload_path(client: TestClient) -> Callable[..., object]:
    """Upload a file from disk and return the raw response."""

    def _upload(
        path: Path,
        filename: str | None = None,
        content_type: str = "application/octet-stream",
    ):
        return client.post(
            "/api/files/",
            files={"file": (filename or path.name, path.read_bytes(), content_type)},
        )

    return _upload


@pytest.fixture()
def upload_bytes(client: TestClient) -> Callable[..., object]:
    """Upload in-memory bytes and return the raw response."""

    def _upload(data: bytes, filename: str, content_type: str = "application/octet-stream"):
        return client.post(
            "/api/files/",
            files={"file": (filename, data, content_type)},
        )

    return _upload
