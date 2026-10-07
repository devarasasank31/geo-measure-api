"""CRS detection and classification tests."""

from __future__ import annotations

import pytest
from pyproj import CRS

from app.services import crs_service


def test_geographic_crs_is_detected() -> None:
    assert crs_service.parse_crs("EPSG:4326") == CRS.from_epsg(4326)
    assert crs_service.crs_label("EPSG:4326") == "EPSG:4326"
    assert crs_service.is_geographic("EPSG:4326")
    assert not crs_service.is_projected("EPSG:4326")
    assert not crs_service.units_are_metres("EPSG:4326")


def test_projected_crs_is_detected() -> None:
    assert crs_service.is_projected("EPSG:32644")
    assert not crs_service.is_geographic("EPSG:32644")
    assert crs_service.units_are_metres("EPSG:32644")
    assert crs_service.crs_label(CRS.from_epsg(32644)) == "EPSG:32644"


def test_missing_crs_is_none() -> None:
    assert crs_service.parse_crs(None) is None
    assert crs_service.crs_label(None) is None
    assert not crs_service.is_geographic(None)
    assert not crs_service.is_projected(None)


def test_unusable_crs_value_is_treated_as_missing() -> None:
    assert crs_service.parse_crs("definitely-not-a-crs") is None
    assert crs_service.crs_label("definitely-not-a-crs") is None


def test_foot_based_projected_crs_is_not_metric() -> None:
    # EPSG:2229 (California zone 5) uses US survey feet.
    assert crs_service.is_projected("EPSG:2229")
    assert not crs_service.units_are_metres("EPSG:2229")


def test_web_mercator_is_recognised() -> None:
    assert crs_service.is_projected("EPSG:3857")
    assert crs_service.units_are_metres("EPSG:3857")
    assert crs_service.is_web_mercator("EPSG:3857")
    assert not crs_service.is_web_mercator("EPSG:32644")


@pytest.mark.parametrize(
    ("crs_value", "geographic", "projected"),
    [
        ("EPSG:4326", True, False),
        ("EPSG:4258", True, False),
        ("EPSG:32643", False, True),
        ("EPSG:32743", False, True),
        ("EPSG:3035", False, True),
        (None, False, False),
    ],
)
def test_classification_of_common_crs(crs_value: str | None, geographic: bool, projected: bool) -> None:
    assert crs_service.is_geographic(crs_value) is geographic
    assert crs_service.is_projected(crs_value) is projected
