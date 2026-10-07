"""CRS detection, classification and projected-CRS selection tests."""

from __future__ import annotations

import geopandas as gpd
import pytest
from pyproj import CRS
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info
from shapely.geometry import box

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


@pytest.mark.parametrize(
    ("longitude", "latitude", "expected_epsg"),
    [
        (78.4, 17.3, 32644),      # Hyderabad
        (-73.98, 40.75, 32618),   # New York
        (2.35, 48.86, 32631),     # Paris
        (-149.9, 61.2, 32606),    # Anchorage
        (151.2, -33.87, 32756),   # Sydney
        (-46.6, -23.5, 32723),    # Sao Paulo
        (174.76, -36.85, 32760),  # Auckland
        (0.0, 0.0, 32631),        # Gulf of Guinea
    ],
)
def test_utm_zone_formula(longitude: float, latitude: float, expected_epsg: int) -> None:
    assert crs_service.utm_epsg_for(longitude, latitude) == expected_epsg


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [
        (78.4, 17.3),
        (-73.98, 40.75),
        (2.35, 48.86),
        (151.2, -33.87),
        (-46.6, -23.5),
        (-157.86, 21.31),
    ],
)
def test_utm_zone_matches_pyproj_database(longitude: float, latitude: float) -> None:
    """Our zone formula must agree with pyproj's UTM lookup."""
    infos = query_utm_crs_info(
        datum_name="WGS 84",
        area_of_interest=AreaOfInterest(
            west_lon_degree=longitude - 0.1,
            south_lat_degree=latitude - 0.1,
            east_lon_degree=longitude + 0.1,
            north_lat_degree=latitude + 0.1,
        ),
    )
    assert infos, "pyproj should find a UTM zone for the test position"
    assert crs_service.utm_epsg_for(longitude, latitude) == int(infos[0].code)


def test_utm_zone_bounds_and_hemisphere() -> None:
    assert crs_service.utm_epsg_for(-180.0, 0.0) == 32601
    assert crs_service.utm_epsg_for(179.99, 0.0) == 32660
    assert crs_service.utm_epsg_for(10.0, -1.0) == 32732  # southern hemisphere
    assert crs_service.utm_epsg_for(10.0, 1.0) == 32632   # northern hemisphere
    assert crs_service.utm_zone_label(32644) == "UTM zone 44N"
    assert crs_service.utm_zone_label(32756) == "UTM zone 56S"


def test_utm_zone_rejects_non_finite_positions() -> None:
    with pytest.raises(ValueError):
        crs_service.utm_epsg_for(float("nan"), 10.0)


def _geographic_gdf(bounds: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[box(*bounds)], crs="EPSG:4326")


def test_geographic_dataset_selects_local_utm_zone() -> None:
    plan = crs_service.build_plan(_geographic_gdf((78.4, 17.3, 78.41, 17.31)))

    assert plan.source_crs == "EPSG:4326"
    assert plan.measurement_crs == "EPSG:32644"
    assert plan.strategy is crs_service.MeasurementStrategy.AUTO_UTM
    assert plan.is_geographic is True
    assert "EPSG:32644" in plan.reason


def test_southern_hemisphere_dataset_selects_southern_zone() -> None:
    plan = crs_service.build_plan(_geographic_gdf((151.2, -33.88, 151.21, -33.87)))

    assert plan.measurement_crs == "EPSG:32756"
    assert plan.strategy is crs_service.MeasurementStrategy.AUTO_UTM


def test_already_projected_metric_crs_is_used_as_is() -> None:
    gdf = _geographic_gdf((78.4, 17.3, 78.41, 17.31)).to_crs("EPSG:32644")

    plan = crs_service.build_plan(gdf)

    assert plan.source_crs == "EPSG:32644"
    assert plan.measurement_crs == "EPSG:32644"
    assert plan.strategy is crs_service.MeasurementStrategy.SOURCE_PROJECTED
    assert plan.is_projected is True


def test_web_mercator_is_replaced_by_local_utm_zone() -> None:
    gdf = _geographic_gdf((78.4, 17.3, 78.41, 17.31)).to_crs("EPSG:3857")

    plan = crs_service.build_plan(gdf)

    assert plan.source_crs == "EPSG:3857"
    assert plan.measurement_crs == "EPSG:32644"
    assert plan.strategy is crs_service.MeasurementStrategy.AUTO_UTM
    assert "Web Mercator" in plan.reason


def test_foot_based_projected_crs_is_replaced() -> None:
    gdf = _geographic_gdf((-118.2, 34.0, -118.1, 34.1)).to_crs("EPSG:2229")

    plan = crs_service.build_plan(gdf)

    assert plan.source_crs == "EPSG:2229"
    assert plan.measurement_crs == "EPSG:32611"
    assert plan.strategy is crs_service.MeasurementStrategy.AUTO_UTM
    assert "foot" in plan.reason


def test_projected_crs_outside_its_area_of_use_is_replaced() -> None:
    # London coordinates forced into an Indian UTM zone: the numbers are far
    # outside the declared area of use of EPSG:32644.
    gdf = _geographic_gdf((-0.13, 51.5, -0.12, 51.51)).to_crs("EPSG:32644")

    plan = crs_service.build_plan(gdf)

    assert plan.source_crs == "EPSG:32644"
    assert plan.measurement_crs == "EPSG:32630"  # London lies just west of 0 deg
    assert plan.strategy is crs_service.MeasurementStrategy.AUTO_UTM
    assert "area of use" in plan.reason


def test_missing_crs_yields_unavailable_plan() -> None:
    gdf = gpd.GeoDataFrame(geometry=[box(78.4, 17.3, 78.41, 17.31)])

    plan = crs_service.build_plan(gdf)

    assert plan.source_crs is None
    assert plan.measurement_crs is None
    assert plan.strategy is crs_service.MeasurementStrategy.UNAVAILABLE
    assert "does not declare" in plan.reason


def test_empty_dataset_yields_unavailable_plan() -> None:
    gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    plan = crs_service.build_plan(gdf)

    assert plan.strategy is crs_service.MeasurementStrategy.UNAVAILABLE
    assert plan.measurement_crs is None


def test_representative_position_converts_projected_centres_to_lon_lat() -> None:
    gdf = _geographic_gdf((78.4, 17.3, 78.41, 17.31)).to_crs("EPSG:32644")

    lon, lat = crs_service.representative_lonlat(gdf)

    assert lon == pytest.approx(78.405, abs=1e-3)
    assert lat == pytest.approx(17.305, abs=1e-3)
