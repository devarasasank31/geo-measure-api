"""End-to-end upload processing tests for KML and Shapefile archives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from fastapi.testclient import TestClient

from app.db import repository
from app.models.schemas import FileStatus


def test_kml_upload_extracts_features(upload_path: Callable, sample_kml: Path) -> None:
    response = upload_path(sample_kml)

    assert response.status_code == 201
    payload = response.json()
    assert payload["feature_count"] == 3
    assert payload["crs"] == "EPSG:4326"
    assert payload["status"] == "COMPLETED"


def test_kml_features_are_persisted(upload_path: Callable, sample_kml: Path) -> None:
    payload = upload_path(sample_kml).json()

    record = repository.get_record(payload["id"])
    assert record is not None

    features = record.features
    assert [f["geometry_type"] for f in features] == ["Polygon", "LineString", "Point"]
    assert [f["feature_id"] for f in features] == [0, 1, 2]
    assert features[0]["properties"]["parcel_id"] == "P-001"
    assert features[0]["crs"] == "EPSG:4326"
    assert features[1]["geometry"]["type"] == "LineString"
    assert features[2]["geometry"]["type"] == "Point"
    json.dumps(features, allow_nan=False)


def test_featureless_kml_succeeds_with_zero_features(upload_bytes: Callable) -> None:
    content = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>empty</name></Document></kml>'
    )

    response = upload_bytes(content, "empty.kml")

    assert response.status_code == 201
    payload = response.json()
    assert payload["feature_count"] == 0
    assert payload["crs"] == "EPSG:4326"
    assert payload["status"] == "COMPLETED"


def test_shapefile_zip_upload_extracts_features(upload_path: Callable, shapefile_zip: Path) -> None:
    response = upload_path(shapefile_zip)

    assert response.status_code == 201
    payload = response.json()
    assert payload["filename"] == "fields.zip"
    assert payload["feature_count"] == 2
    assert payload["crs"] == "EPSG:4326"
    assert payload["status"] == "COMPLETED"


def test_shapefile_zip_features_keep_attributes(upload_path: Callable, shapefile_zip: Path) -> None:
    payload = upload_path(shapefile_zip).json()

    record = repository.get_record(payload["id"])
    assert record is not None

    features = record.features
    assert [f["geometry_type"] for f in features] == ["Polygon", "Polygon"]
    assert features[0]["properties"] == {"name": "North Field", "code": 101}
    assert features[1]["properties"]["name"] == "South Field"
    json.dumps(features, allow_nan=False)


def test_shapefile_extraction_directory_is_cleaned_up(
    upload_path: Callable, shapefile_zip: Path
) -> None:
    payload = upload_path(shapefile_zip).json()

    record = repository.get_record(payload["id"])
    assert record is not None
    stored = Path(record.stored_path)

    assert stored.exists()
    assert not (stored.parent / "extracted").exists()


def test_zip_without_shapefile_is_rejected(
    upload_bytes: Callable, make_zip_bytes: Callable
) -> None:
    response = upload_bytes(make_zip_bytes({"readme.txt": b"hello"}), "docs.zip")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NO_SHAPEFILE_IN_ARCHIVE"

    records = repository.list_records()
    assert len(records) == 1
    assert records[0].status == FileStatus.FAILED
    assert records[0].error_message


def test_corrupt_zip_fails_cleanly_during_processing(upload_bytes: Callable) -> None:
    payload = b"PK\x03\x04" + b"garbage" * 40

    response = upload_bytes(payload, "corrupt.zip")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CORRUPT_ARCHIVE"
    assert repository.list_records()[0].status == FileStatus.FAILED


def test_malformed_kml_returns_clean_error_and_failed_record(upload_bytes: Callable) -> None:
    response = upload_bytes(
        b"<kml><Document><Placemark><Polygon></Document>", "broken.kml"
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "MALFORMED_INPUT"
    assert "Traceback" not in error["message"]

    records = repository.list_records()
    assert len(records) == 1
    assert records[0].status == FileStatus.FAILED
    assert records[0].error_message == error["message"]


def test_processing_failure_keeps_the_stored_file(upload_bytes: Callable) -> None:
    upload_bytes(b"<kml><Document><Placemark><Polygon></Document>", "broken.kml")

    record = repository.list_records()[0]
    assert Path(record.stored_path).exists()
