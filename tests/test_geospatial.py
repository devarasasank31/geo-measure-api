"""Vector reading and feature extraction tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box

from app.models.schemas import Feature
from app.services import geospatial_service


@pytest.fixture()
def shapefile_path(tmp_path: Path) -> Path:
    gdf = gpd.GeoDataFrame(
        {"name": ["Parcel A"], "area_code": [17]},
        geometry=[box(78.4, 17.3, 78.41, 17.31)],
        crs="EPSG:4326",
    )
    path = tmp_path / "parcel.shp"
    gdf.to_file(path)
    return path


def dumps(value: Any) -> str:
    return json.dumps(value, allow_nan=False)


def test_read_shapefile_returns_dataframe_with_crs(shapefile_path: Path) -> None:
    gdf = geospatial_service.read_shapefile(shapefile_path)

    assert len(gdf) == 1
    assert geospatial_service.crs_label(gdf) == "EPSG:4326"
    assert list(gdf.columns) == ["name", "area_code", "geometry"]


def test_read_shapefile_rejects_missing_file(tmp_path: Path) -> None:
    from app.core.exceptions import AppException

    with pytest.raises(AppException) as excinfo:
        geospatial_service.read_shapefile(tmp_path / "nope.shp")

    assert excinfo.value.code == "MALFORMED_INPUT"
    assert excinfo.value.status_code == 422


def test_build_features_extracts_geometry_type_properties_and_crs(
    shapefile_path: Path,
) -> None:
    gdf = geospatial_service.read_shapefile(shapefile_path)

    features = geospatial_service.build_features(gdf)

    assert len(features) == 1
    feature = features[0]
    assert isinstance(feature, Feature)
    assert feature.feature_id == 0
    assert feature.geometry_type == "Polygon"
    assert feature.crs == "EPSG:4326"
    assert feature.properties == {"name": "Parcel A", "area_code": 17}
    assert feature.geometry is not None
    assert feature.geometry["type"] == "Polygon"
    assert len(feature.geometry["coordinates"][0]) == 5
    dumps([f.model_dump() for f in features])


def test_build_features_handles_mixed_geometry_types(tmp_path: Path) -> None:
    gdf = gpd.GeoDataFrame(
        {"kind": ["area", "route", "marker"]},
        geometry=[box(0, 0, 1, 1), LineString([(0, 0), (2, 2)]), Point(5, 5)],
        crs="EPSG:4326",
    )

    features = geospatial_service.build_features(gdf)

    assert [f.geometry_type for f in features] == ["Polygon", "LineString", "Point"]
    assert [f.feature_id for f in features] == [0, 1, 2]
    dumps([f.model_dump() for f in features])


def test_build_features_handles_missing_geometry() -> None:
    gdf = gpd.GeoDataFrame({"name": ["ghost"]}, geometry=[None], crs="EPSG:4326")

    features = geospatial_service.build_features(gdf)

    assert features[0].geometry_type == "Null"
    assert features[0].geometry is None
    dumps([f.model_dump() for f in features])


def test_build_features_uses_positional_ids() -> None:
    gdf = gpd.GeoDataFrame(
        {"name": ["a", "b"]},
        geometry=[Point(0, 0), Point(1, 1)],
        crs="EPSG:4326",
        index=[10, 20],
    )

    features = geospatial_service.build_features(gdf)

    assert [f.feature_id for f in features] == [0, 1]


def test_crs_label_is_none_when_crs_missing() -> None:
    gdf = gpd.GeoDataFrame({"name": ["x"]}, geometry=[Point(0, 0)])

    assert geospatial_service.crs_label(gdf) is None
    features = geospatial_service.build_features(gdf)
    assert features[0].crs is None


def test_read_kml_reports_wgs84_crs(sample_kml: Path) -> None:
    gdf = geospatial_service.read_kml(sample_kml)

    assert len(gdf) == 3
    assert geospatial_service.crs_label(gdf) == "EPSG:4326"


def test_read_kml_extracts_features_and_extended_data(sample_kml: Path) -> None:
    gdf = geospatial_service.read_kml(sample_kml)

    features = geospatial_service.build_features(gdf)

    assert [f.geometry_type for f in features] == ["Polygon", "LineString", "Point"]
    assert features[0].properties["Name"] == "North Plot"
    assert features[0].properties["parcel_id"] == "P-001"
    assert features[0].properties["zone"] == "residential"
    assert features[2].properties["Name"] == "Survey Marker"
    dumps([f.model_dump() for f in features])


def test_read_kml_malformed_raises_clean_error(tmp_path: Path) -> None:
    from app.core.exceptions import AppException

    broken = tmp_path / "broken.kml"
    broken.write_text("<kml><Document><Placemark><Polygon></Document>", encoding="utf-8")

    with pytest.raises(AppException) as excinfo:
        geospatial_service.read_kml(broken)

    assert excinfo.value.code == "MALFORMED_INPUT"
    assert excinfo.value.status_code == 422


def test_read_kml_without_features_returns_empty_frame(tmp_path: Path) -> None:
    featureless = tmp_path / "featureless.kml"
    featureless.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>empty</name></Document></kml>',
        encoding="utf-8",
    )

    gdf = geospatial_service.read_kml(featureless)

    assert len(gdf) == 0
    assert geospatial_service.crs_label(gdf) == "EPSG:4326"
    assert geospatial_service.build_features(gdf) == []


def test_read_kml_falls_back_to_fiona_engine(
    sample_kml: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(geospatial_service, "_READ_ENGINES", ("fiona",))

    gdf = geospatial_service.read_kml(sample_kml)

    assert len(gdf) == 3
    assert geospatial_service.crs_label(gdf) == "EPSG:4326"
