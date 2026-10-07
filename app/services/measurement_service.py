"""Per-feature measurements (area and length) computed in a projected CRS.

The measurement service never decides *which* CRS to use: that is the job of
:class:`app.services.crs_service`. It receives geometries that have already
been transformed into a metric CRS, or ``None`` when no safe CRS exists, and
reports a status for every feature so a single unsupported or broken geometry
cannot fail a whole file.
"""

from __future__ import annotations

import logging

import geopandas as gpd

from app.core.config import settings
from app.models.schemas import Measurement, MeasurementStatus
from app.services.crs_service import CrsPlan
from app.utils.geometry_utils import geometry_type_of

logger = logging.getLogger(__name__)

AREA_UNIT = "m²"
LENGTH_UNIT = "m"

#: Geometry types measured as an area.
_POLYGONAL_TYPES = frozenset({"Polygon", "MultiPolygon"})
#: Geometry types measured as a length.
_LINEAR_TYPES = frozenset({"LineString", "MultiLineString", "LinearRing"})
#: Geometry types that need no measurement.
_POINT_TYPES = frozenset({"Point", "MultiPoint"})


def compute_measurements(
    source_gdf: gpd.GeoDataFrame,
    measured_gdf: gpd.GeoDataFrame | None,
    plan: CrsPlan,
) -> list[Measurement]:
    """Return exactly one measurement entry per source feature.

    ``measured_gdf`` contains the same features transformed into the
    measurement CRS. When it is ``None`` (missing or unusable CRS) no
    measurement is attempted and each entry explains why.
    """
    results: list[Measurement] = []
    measured = measured_gdf is not None

    for position in range(len(source_gdf)):
        source_geometry = source_gdf.iloc[position].geometry
        geometry_type = geometry_type_of(source_geometry)
        geometry = measured_gdf.iloc[position].geometry if measured else None
        results.append(
            _measure_feature(
                feature_id=position,
                geometry_type=geometry_type,
                geometry=geometry,
                source_is_null=source_geometry is None,
                plan=plan,
                measured=measured,
            )
        )

    logger.info(
        "Computed %d measurement entr%s (%s)",
        len(results),
        "y" if len(results) == 1 else "ies",
        _summarise(results),
    )
    return results


def _measure_feature(
    *,
    feature_id: int,
    geometry_type: str,
    geometry: object,
    source_is_null: bool,
    plan: CrsPlan,
    measured: bool,
) -> Measurement:
    """Measure one feature, translating any failure into a status."""
    if source_is_null or geometry_type == "Null":
        return Measurement(
            feature_id=feature_id,
            geometry_type=geometry_type,
            measurement=None,
            measurement_unit=None,
            status=MeasurementStatus.NULL_GEOMETRY,
            detail="The feature has no geometry to measure.",
        )

    if not measured or geometry is None:
        return Measurement(
            feature_id=feature_id,
            geometry_type=geometry_type,
            measurement=None,
            measurement_unit=None,
            status=MeasurementStatus.CRS_MISSING,
            detail=plan.reason,
        )

    if geometry_type in _POLYGONAL_TYPES:
        return _compute(feature_id, geometry_type, geometry, kind="area", unit=AREA_UNIT)
    if geometry_type in _LINEAR_TYPES:
        return _compute(feature_id, geometry_type, geometry, kind="length", unit=LENGTH_UNIT)
    if geometry_type in _POINT_TYPES:
        return Measurement(
            feature_id=feature_id,
            geometry_type=geometry_type,
            measurement=None,
            measurement_unit=None,
            status=MeasurementStatus.NOT_REQUIRED,
            detail="Points have no measurable area or length.",
        )
    return Measurement(
        feature_id=feature_id,
        geometry_type=geometry_type,
        measurement=None,
        measurement_unit=None,
        status=MeasurementStatus.UNSUPPORTED,
        detail=f"{geometry_type} geometries are not measured.",
    )


def _compute(
    feature_id: int,
    geometry_type: str,
    geometry: object,
    *,
    kind: str,
    unit: str,
) -> Measurement:
    """Compute ``area`` or ``length`` and round the result."""
    try:
        if not geometry.is_valid:
            logger.warning(
                "Feature %d has an invalid %s geometry; measuring it anyway",
                feature_id,
                geometry_type,
            )
        raw_value = geometry.area if kind == "area" else geometry.length
        value = round(float(raw_value), settings.measurement_decimals)
    except Exception:
        logger.exception("Failed to compute %s for feature %d", kind, feature_id)
        return Measurement(
            feature_id=feature_id,
            geometry_type=geometry_type,
            measurement=None,
            measurement_unit=None,
            status=MeasurementStatus.ERROR,
            detail="The measurement could not be computed for this feature.",
        )

    return Measurement(
        feature_id=feature_id,
        geometry_type=geometry_type,
        measurement=value,
        measurement_unit=unit,
        status=MeasurementStatus.COMPLETED,
    )


def _summarise(measurements: list[Measurement]) -> str:
    counts: dict[MeasurementStatus, int] = {}
    for measurement in measurements:
        counts[measurement.status] = counts.get(measurement.status, 0) + 1
    return ", ".join(f"{status.value}={count}" for status, count in sorted(counts.items()))
