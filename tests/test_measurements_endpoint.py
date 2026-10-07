"""Measurements endpoint tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from fastapi.testclient import TestClient

from app.models.schemas import Measurement, MeasurementStatus, MeasurementsResponse


def test_measurements_endpoint_returns_spec_shape(
    client: TestClient, upload_path: Callable, sample_kml: Path
) -> None:
    file_id = upload_path(sample_kml).json()["id"]

    response = client.get(f"/api/files/{file_id}/measurements/")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "file_id",
        "source_crs",
        "measurement_crs",
        "measurement_strategy",
        "measurements",
    }
    assert payload["file_id"] == file_id
    assert payload["source_crs"] == "EPSG:4326"
    assert payload["measurement_crs"] == "EPSG:32644"

    validated = MeasurementsResponse.model_validate(payload)
    assert [m.status for m in validated.measurements] == [
        MeasurementStatus.COMPLETED,
        MeasurementStatus.COMPLETED,
        MeasurementStatus.NOT_REQUIRED,
    ]
    json.dumps(payload, allow_nan=False)


def test_measurements_endpoint_returns_area_and_length_values(
    client: TestClient, upload_path: Callable, sample_kml: Path
) -> None:
    file_id = upload_path(sample_kml).json()["id"]

    measurements = client.get(f"/api/files/{file_id}/measurements/").json()["measurements"]

    polygon, line, point = measurements
    assert polygon["geometry_type"] == "Polygon"
    assert polygon["measurement_unit"] == "m²"
    assert polygon["measurement"] > 0
    assert line["geometry_type"] == "LineString"
    assert line["measurement_unit"] == "m"
    assert line["measurement"] > 0
    assert point["geometry_type"] == "Point"
    assert point["status"] == "NOT_REQUIRED"
    assert point["measurement"] is None
    assert point["measurement_unit"] is None


def test_measurements_endpoint_for_missing_crs_file(
    client: TestClient, upload_path: Callable, shapefile_zip_without_crs: Path
) -> None:
    file_id = upload_path(shapefile_zip_without_crs).json()["id"]

    payload = client.get(f"/api/files/{file_id}/measurements/").json()

    assert payload["source_crs"] is None
    assert payload["measurement_crs"] is None
    assert payload["measurement_strategy"] == "UNAVAILABLE"
    assert [m["status"] for m in payload["measurements"]] == ["CRS_MISSING"]
    assert payload["measurements"][0]["detail"]


def test_measurements_endpoint_unknown_id_returns_404(client: TestClient) -> None:
    response = client.get("/api/files/00000000000000000000000000000000/measurements/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_measurements_survive_serialisation_for_mixed_geometries(
    client: TestClient, upload_path: Callable, fixtures_dir: Path
) -> None:
    file_id = upload_path(fixtures_dir / "mixed_geometry.kml").json()["id"]

    payload = client.get(f"/api/files/{file_id}/measurements/").json()

    measurements = [Measurement.model_validate(item) for item in payload["measurements"]]
    assert {m.status for m in measurements} == {
        MeasurementStatus.COMPLETED,
        MeasurementStatus.UNSUPPORTED,
        MeasurementStatus.NOT_REQUIRED,
    }
    json.dumps(payload, allow_nan=False)
