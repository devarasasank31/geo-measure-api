"""Feature serialisation tests: geometries, properties and schemas."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from app.models.schemas import Feature
from app.utils.serialization import (
    geometry_to_geojson,
    is_null,
    json_safe,
    properties_to_dict,
)


def dumps(value: Any) -> str:
    """Serialise strictly: ``allow_nan=False`` rejects invalid JSON numbers."""
    return json.dumps(value, allow_nan=False)


def test_polygon_becomes_geojson_coordinates_lists() -> None:
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])

    geojson = geometry_to_geojson(polygon)

    assert geojson is not None
    assert geojson["type"] == "Polygon"
    assert isinstance(geojson["coordinates"], list)
    assert all(isinstance(ring, list) for ring in geojson["coordinates"])
    assert isinstance(geojson["coordinates"][0][0], list)
    assert dumps(geojson)


def test_linestring_and_point_serialise() -> None:
    linestring = LineString([(0, 0), (2, 2)])
    point = Point(5, 6)

    assert geometry_to_geojson(linestring)["type"] == "LineString"
    assert geometry_to_geojson(point) == {
        "type": "Point",
        "coordinates": [5.0, 6.0],
    }


def test_null_geometry_returns_none() -> None:
    assert geometry_to_geojson(None) is None


def test_json_safe_converts_numpy_scalars() -> None:
    payload = {
        "count": np.int64(42),
        "ratio": np.float64(1.5),
        "flag": np.bool_(True),
        "short": np.int16(3),
    }

    result = json_safe(payload)

    assert result == {"count": 42, "ratio": 1.5, "flag": True, "short": 3}
    assert dumps(result)


def test_json_safe_turns_nan_and_inf_into_null() -> None:
    assert json_safe(float("nan")) is None
    assert json_safe(float("inf")) is None
    assert dumps(json_safe({"a": np.float32("nan"), "b": 1.0}))


def test_json_safe_handles_dates_bytes_and_paths() -> None:
    assert json_safe(datetime(2024, 5, 1, 12, 30)) == "2024-05-01T12:30:00"
    assert json_safe(b"binary") == "binary"
    assert json_safe(pd.Timestamp("2024-05-01")) == "2024-05-01T00:00:00"
    assert json_safe(object())  # falls back to a string


def test_is_null_detects_missing_markers() -> None:
    assert is_null(None)
    assert is_null(float("nan"))
    assert is_null(pd.NaT)
    assert is_null(np.float64("nan"))
    assert not is_null(0)
    assert not is_null("")
    assert not is_null(False)


def test_properties_drop_missing_values_but_keep_zero_and_empty_string() -> None:
    properties = {
        "name": "Plot A",
        "area": 0,
        "note": "",
        "missing": None,
        "nan_value": np.float64("nan"),
        "timestamp": pd.NaT,
        "zone": "residential",
    }

    result = properties_to_dict(properties)

    assert result == {"name": "Plot A", "area": 0, "note": "", "zone": "residential"}
    assert dumps(result)


def test_properties_preserve_attribute_types() -> None:
    properties = {"parcel_id": "P-001", "length_m": np.float64(12.5), "surveyed": np.bool_(1)}

    result = properties_to_dict(properties)

    assert result == {"parcel_id": "P-001", "length_m": 12.5, "surveyed": True}
    assert dumps(result)


def test_feature_schema_round_trips_to_json() -> None:
    feature = Feature(
        feature_id=0,
        geometry_type="Polygon",
        geometry=geometry_to_geojson(Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])),
        crs="EPSG:4326",
        properties={"name": "Plot A"},
    )

    payload = feature.model_dump()

    assert payload["feature_id"] == 0
    assert payload["properties"] == {"name": "Plot A"}
    assert dumps(payload)


def test_feature_schema_allows_missing_geometry_and_properties() -> None:
    feature = Feature(feature_id=3, geometry_type="Null")

    payload = feature.model_dump()
    assert payload["geometry"] is None
    assert payload["crs"] is None
    assert payload["properties"] == {}
    assert dumps(payload)
