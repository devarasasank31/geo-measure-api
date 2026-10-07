"""Upload endpoint tests: validation, size limits and safe storage."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db import repository


def test_upload_kml_returns_created(client: TestClient, upload_path: Callable, sample_kml: Path) -> None:
    response = upload_path(sample_kml)

    assert response.status_code == 201
    payload = response.json()
    assert set(payload) == {"id", "filename", "feature_count", "crs", "status"}
    assert payload["filename"] == "sample.kml"
    assert payload["status"] == "COMPLETED"
    assert isinstance(payload["id"], str) and len(payload["id"]) >= 16


def test_upload_rejects_unsupported_extension(upload_bytes: Callable) -> None:
    response = upload_bytes(b"hello world", "notes.txt")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_rejects_file_without_extension(upload_bytes: Callable) -> None:
    response = upload_bytes(b"<kml></kml>", "README")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_rejects_empty_file(upload_bytes: Callable) -> None:
    response = upload_bytes(b"", "empty.kml")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_FILE"


def test_upload_rejects_oversized_file(
    upload_bytes: Callable, app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_settings, "max_upload_mb", 1)
    payload = b"<kml>" + b"a" * (1024 * 1024 + 1024)

    response = upload_bytes(payload, "huge.kml")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_upload_requires_file_field(client: TestClient) -> None:
    response = client.post("/api/files/", data={"not_the_file": "x"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_upload_sanitizes_filename_and_stores_in_its_own_directory(
    client: TestClient,
    upload_path: Callable,
    app_settings: Settings,
    sample_kml: Path,
) -> None:
    response = upload_path(sample_kml, filename="../../../etc/passwd.kml")

    assert response.status_code == 201
    payload = response.json()
    assert payload["filename"] == "passwd.kml"

    record = repository.get_record(payload["id"])
    assert record is not None
    stored = Path(record.stored_path)
    assert stored.resolve().is_relative_to(app_settings.upload_dir.resolve())
    assert stored.exists()
    assert stored.read_bytes() == sample_kml.read_bytes()


def test_upload_rejects_file_with_wrong_extension_casing_is_allowed(
    upload_path: Callable, sample_kml: Path
) -> None:
    """Extensions are matched case-insensitively."""
    response = upload_path(sample_kml, filename="SAMPLE.KML")

    assert response.status_code == 201
    assert response.json()["filename"] == "SAMPLE.KML"


def test_upload_rejects_non_zip_content(upload_bytes: Callable) -> None:
    response = upload_bytes(b"this is definitely not an archive", "data.zip")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CORRUPT_ARCHIVE"


def test_upload_rejects_non_xml_kml_content(upload_bytes: Callable) -> None:
    response = upload_bytes(b"\x00\x01\x02 binary rubbish", "survey.kml")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE_CONTENT"


def test_stored_file_leaves_nothing_behind_after_rejection(upload_bytes: Callable, app_settings: Settings) -> None:
    response = upload_bytes(b"", "empty.kml")

    assert response.status_code == 400
    upload_root = app_settings.upload_dir
    if upload_root.exists():
        assert list(upload_root.iterdir()) == []
