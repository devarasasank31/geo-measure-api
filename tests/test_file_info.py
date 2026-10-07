"""File information endpoint and general API response tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from fastapi.testclient import TestClient

from app.models.schemas import (
    Feature,
    FileInfoResponse,
    FileStatus,
    FileUploadResponse,
)


def test_file_info_endpoint_returns_full_metadata(
    client: TestClient, upload_path: Callable, sample_kml: Path
) -> None:
    file_id = upload_path(sample_kml).json()["id"]

    response = client.get(f"/api/files/{file_id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == file_id
    assert payload["filename"] == "sample.kml"
    assert payload["feature_count"] == 3
    assert payload["crs"] == "EPSG:4326"
    assert payload["measurement_crs"] == "EPSG:32644"
    assert payload["measurement_strategy"] == "AUTO_UTM"
    assert payload["status"] == "COMPLETED"
    assert payload["format"] == "kml"
    assert payload["size_bytes"] > 0
    assert payload["error"] is None
    assert payload["created_at"]

    info = FileInfoResponse.model_validate(payload)
    assert info.status is FileStatus.COMPLETED


def test_file_info_includes_features_with_geometry_and_properties(
    client: TestClient, upload_path: Callable, sample_kml: Path
) -> None:
    file_id = upload_path(sample_kml).json()["id"]

    payload = client.get(f"/api/files/{file_id}/").json()

    assert len(payload["features"]) == 3
    feature = Feature.model_validate(payload["features"][0])
    assert feature.feature_id == 0
    assert feature.geometry_type == "Polygon"
    assert feature.crs == "EPSG:4326"
    assert feature.properties["parcel_id"] == "P-001"
    assert feature.geometry["type"] == "Polygon"
    assert isinstance(feature.geometry["coordinates"], list)
    # Every response must be strictly JSON serialisable.
    json.dumps(payload, allow_nan=False)


def test_file_info_for_shapefile_zip(
    client: TestClient, upload_path: Callable, shapefile_zip: Path
) -> None:
    file_id = upload_path(shapefile_zip).json()["id"]

    payload = client.get(f"/api/files/{file_id}/").json()

    assert payload["format"] == "zip"
    assert payload["feature_count"] == 2
    assert payload["features"][0]["properties"]["name"] == "North Field"


def test_file_info_unknown_id_returns_404(client: TestClient) -> None:
    response = client.get("/api/files/does-not-exist/")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "FILE_NOT_FOUND"
    assert "Traceback" not in error["message"]


def test_unknown_route_returns_structured_error(client: TestClient) -> None:
    response = client.get("/api/nope/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_upload_response_validates_against_schema(
    upload_path: Callable, sample_kml: Path
) -> None:
    payload = upload_path(sample_kml).json()

    upload = FileUploadResponse.model_validate(payload)
    assert upload.status is FileStatus.COMPLETED
    assert upload.feature_count == 3


def test_failed_processing_file_exposes_clean_error_not_traceback(
    upload_bytes: Callable,
) -> None:
    response = upload_bytes(b"<kml><Document><Placemark><Polygon></Document>", "broken.kml")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "MALFORMED_INPUT"
    assert "Traceback" not in body["error"]["message"]
    assert 'File "' not in body["error"]["message"]
