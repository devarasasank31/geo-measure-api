"""Shared pytest fixtures.

Every test gets an isolated upload directory and SQLite database, so tests
never touch real application data.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings


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
