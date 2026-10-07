"""Measurement tests: area, length, points and unsupported geometries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import geopandas as gpd
import pytest
from pyproj import Geod
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)

from app.db import repository
from app.models.schemas import Measurement, MeasurementStatus
from app.services import crs_service, measurement_service

GEOD = Geod(ellps="WGS84")


def measure(gdf: gpd.GeoDataFrame) -> list[Measurement]:
    """Run the real plan -> transform -> measure pipeline."""
    plan = crs_service.build_plan(gdf)
    measured = crs_service.transform_for_measurement(gdf, plan)
    return measurement_service.compute_measurements(gdf, measured, plan)


@pytest.fixture()
def mixed_geometry_kml(fixtures_dir: Path) -> Path:
    return fixtures_dir / "mixed_geometry.kml"


def test_polygon_area_is_measured_in_square_metres() -> None:
    # A 200 m x 150 m rectangle defined in UTM, read back as degrees.
    rectangle = gpd.GeoDataFrame(
        geometry=[box(500_000, 1_900_000, 500_200, 1_900_150)],
        crs="EPSG:32644",
    ).to_crs("EPSG:4326")

    results = measure(rectangle)

    assert results[0].status is MeasurementStatus.COMPLETED
    assert results[0].geometry_type == "Polygon"
    assert results[0].measurement_unit == "m²"
    assert results[0].measurement == pytest.approx(30_000.0, rel=0.01)


def test_polygon_area_agrees_with_geodesic_area() -> None:
    polygon = Polygon(
        [
            (78.4000, 17.3000),
            (78.4100, 17.3000),
            (78.4100, 17.3100),
            (78.4000, 17.3100),
        ]
    )
    gdf = gpd.GeoDataFrame(geometry=[polygon], crs="EPSG:4326")
    geodesic_area, _ = GEOD.geometry_area_perimeter(polygon)

    results = measure(gdf)

    assert results[0].status is MeasurementStatus.COMPLETED
    assert results[0].measurement == pytest.approx(abs(geodesic_area), rel=0.01)


def test_linestring_length_is_measured_in_metres() -> None:
    line = LineString([(78.4000, 17.3000), (78.4050, 17.3050)])
    gdf = gpd.GeoDataFrame(geometry=[line], crs="EPSG:4326")
    geodesic_length = GEOD.geometry_length(line)

    results = measure(gdf)

    assert results[0].status is MeasurementStatus.COMPLETED
    assert results[0].geometry_type == "LineString"
    assert results[0].measurement_unit == "m"
    assert results[0].measurement == pytest.approx(geodesic_length, rel=0.01)


def test_point_requires_no_measurement() -> None:
    gdf = gpd.GeoDataFrame(geometry=[Point(78.4, 17.3)], crs="EPSG:4326")

    results = measure(gdf)

    assert results[0].status is MeasurementStatus.NOT_REQUIRED
    assert results[0].measurement is None
    assert results[0].measurement_unit is None
    assert results[0].detail


def test_multi_polygon_and_multi_line_string_are_measured() -> None:
    multi_polygon = MultiPolygon([box(78.40, 17.30, 78.41, 17.31), box(78.42, 17.32, 78.43, 17.33)])
    multi_line = MultiLineString(
        [((78.40, 17.30), (78.41, 17.31)), ((78.42, 17.32), (78.43, 17.33))]
    )
    gdf = gpd.GeoDataFrame(geometry=[multi_polygon, multi_line], crs="EPSG:4326")

    results = measure(gdf)

    assert results[0].status is MeasurementStatus.COMPLETED
    assert results[0].geometry_type == "MultiPolygon"
    assert results[0].measurement_unit == "m²"
    assert results[1].status is MeasurementStatus.COMPLETED
    assert results[1].geometry_type == "MultiLineString"
    assert results[1].measurement_unit == "m"


def test_geometry_collection_is_reported_as_unsupported() -> None:
    collection = GeometryCollection(
        [box(78.40, 17.30, 78.41, 17.31), LineString([(78.40, 17.30), (78.41, 17.31)])]
    )
    gdf = gpd.GeoDataFrame(geometry=[collection], crs="EPSG:4326")

    results = measure(gdf)

    assert results[0].status is MeasurementStatus.UNSUPPORTED
    assert results[0].geometry_type == "GeometryCollection"
    assert results[0].measurement is None
    assert results[0].measurement_unit is None
    assert results[0].detail


def test_null_geometry_has_its_own_status() -> None:
    gdf = gpd.GeoDataFrame({"name": ["ghost"]}, geometry=[None], crs="EPSG:4326")

    results = measure(gdf)

    assert results[0].status is MeasurementStatus.NULL_GEOMETRY
    assert results[0].geometry_type == "Null"
    assert results[0].measurement is None


def test_missing_crs_reports_crs_missing_and_never_measures_degrees() -> None:
    gdf = gpd.GeoDataFrame(
        geometry=[box(78.40, 17.30, 78.41, 17.31), LineString([(78.40, 17.30), (78.41, 17.31)])]
    )

    results = measure(gdf)

    assert [r.status for r in results] == [
        MeasurementStatus.CRS_MISSING,
        MeasurementStatus.CRS_MISSING,
    ]
    assert all(r.measurement is None for r in results)
    assert all("coordinate reference system" in (r.detail or "") for r in results)


def test_one_unsupported_feature_does_not_stop_the_others() -> None:
    gdf = gpd.GeoDataFrame(
        geometry=[
            box(78.40, 17.30, 78.41, 17.31),
            GeometryCollection([Point(78.4, 17.3)]),
            LineString([(78.40, 17.30), (78.41, 17.31)]),
            None,
        ],
        crs="EPSG:4326",
    )

    results = measure(gdf)

    assert [r.status for r in results] == [
        MeasurementStatus.COMPLETED,
        MeasurementStatus.UNSUPPORTED,
        MeasurementStatus.COMPLETED,
        MeasurementStatus.NULL_GEOMETRY,
    ]
    assert [r.feature_id for r in results] == [0, 1, 2, 3]


def test_invalid_polygon_is_measured_without_crashing() -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    gdf = gpd.GeoDataFrame(geometry=[bowtie], crs="EPSG:4326")

    results = measure(gdf)

    assert results[0].status is MeasurementStatus.COMPLETED
    assert results[0].measurement is not None


def test_kml_upload_measurements_are_computed(upload_path: Callable, sample_kml: Path) -> None:
    payload = upload_path(sample_kml).json()

    record = repository.get_record(payload["id"])
    assert record is not None
    assert record.measurement_crs == "EPSG:32644"
    assert record.measurement_strategy == "AUTO_UTM"

    measurements = record.measurements
    json.dumps(measurements, allow_nan=False)

    assert [m["status"] for m in measurements] == [
        "COMPLETED",
        "COMPLETED",
        "NOT_REQUIRED",
    ]
    assert measurements[0]["measurement_unit"] == "m²"
    assert measurements[0]["measurement"] > 0
    assert measurements[1]["measurement_unit"] == "m"
    assert measurements[1]["measurement"] > 0
    assert measurements[2]["measurement"] is None


def test_kml_measurements_match_geodesic_reference(upload_path: Callable, sample_kml: Path) -> None:
    payload = upload_path(sample_kml).json()

    record = repository.get_record(payload["id"])
    assert record is not None
    features = record.features
    measurements = record.measurements

    from shapely.geometry import shape

    polygon = shape(features[0]["geometry"])
    line = shape(features[1]["geometry"])
    polygon_area, _ = GEOD.geometry_area_perimeter(polygon)

    assert measurements[0]["measurement"] == pytest.approx(abs(polygon_area), rel=0.02)
    assert measurements[1]["measurement"] == pytest.approx(
        GEOD.geometry_length(line), rel=0.02
    )


def test_shapefile_zip_measurements(upload_path: Callable, shapefile_zip: Path) -> None:
    payload = upload_path(shapefile_zip).json()

    record = repository.get_record(payload["id"])
    assert record is not None

    assert record.measurement_crs == "EPSG:32644"
    measurements = record.measurements
    assert len(measurements) == 2
    assert all(m["status"] == "COMPLETED" for m in measurements)
    assert all(m["measurement_unit"] == "m²" for m in measurements)
    # Each fixture parcel is roughly 1.1 km x 1.1 km.
    assert all(1_000_000 < m["measurement"] < 1_500_000 for m in measurements)


def test_missing_crs_shapefile_reports_unavailable_measurements(
    upload_path: Callable, shapefile_zip_without_crs: Path
) -> None:
    payload = upload_path(shapefile_zip_without_crs).json()

    assert payload["status"] == "COMPLETED"
    assert payload["crs"] is None
    assert payload["feature_count"] == 1

    record = repository.get_record(payload["id"])
    assert record is not None
    assert record.source_crs is None
    assert record.measurement_crs is None
    assert record.measurement_strategy == "UNAVAILABLE"

    measurements = record.measurements
    assert [m["status"] for m in measurements] == ["CRS_MISSING"]
    assert measurements[0]["measurement"] is None
    assert measurements[0]["detail"]


def test_mixed_geometry_kml_is_processed_without_crashing(
    upload_path: Callable, mixed_geometry_kml: Path
) -> None:
    payload = upload_path(mixed_geometry_kml)

    assert payload.status_code == 201
    body = payload.json()
    assert body["status"] == "COMPLETED"
    assert body["feature_count"] == 4

    record = repository.get_record(body["id"])
    assert record is not None

    measurements = record.measurements
    assert [m["geometry_type"] for m in measurements] == [
        "MultiPolygon",
        "MultiLineString",
        "GeometryCollection",
        "Point",
    ]
    assert [m["status"] for m in measurements] == [
        "COMPLETED",
        "COMPLETED",
        "UNSUPPORTED",
        "NOT_REQUIRED",
    ]
    json.dumps(measurements, allow_nan=False)
