"""Coordinate reference system detection, selection and transformation.

Measurements must never be computed on longitude/latitude degrees: one
degree of latitude is roughly 111 km, and one degree of longitude shrinks
towards the poles, so ``geometry.area`` on geographic coordinates returns
meaningless "square degrees". This module decides which projected CRS is
suitable for a dataset and transforms geometries into it.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum

import geopandas as gpd
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

logger = logging.getLogger(__name__)

#: Unit names pyproj uses for metre-based axes.
_METRE_UNITS = frozenset({"metre", "meter", "m"})

#: Web Mercator pseudo-projection: technically metres, but heavily distorted.
_WEB_MERCATOR_EPSGS = frozenset({3857, 900913, 3785})


class MeasurementStrategy(str, Enum):
    """How (and whether) a dataset can be measured."""

    AUTO_UTM = "AUTO_UTM"
    SOURCE_PROJECTED = "SOURCE_PROJECTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CrsPlan:
    """Decision about the CRS to use for measurements of one dataset."""

    source_crs: str | None
    measurement_crs: str | None
    strategy: MeasurementStrategy
    is_geographic: bool
    is_projected: bool
    reason: str


def parse_crs(value: object) -> CRS | None:
    """Interpret any CRS-like input (``CRS``, ``"EPSG:4326"``, WKT, ...)."""
    if value is None:
        return None
    if isinstance(value, CRS):
        return value
    try:
        return CRS.from_user_input(value)
    except (CRSError, ValueError, TypeError) as exc:
        logger.warning("Ignoring unusable CRS value %r: %s", value, exc)
        return None


def crs_label(value: object) -> str | None:
    """Return a compact label such as ``EPSG:4326``, or ``None``."""
    parsed = parse_crs(value)
    return parsed.to_string() if parsed is not None else None


def is_geographic(value: object) -> bool:
    """True when the CRS is angular (coordinates are degrees)."""
    parsed = parse_crs(value)
    return bool(parsed is not None and parsed.is_geographic)


def is_projected(value: object) -> bool:
    """True when the CRS is planar (coordinates are linear units)."""
    parsed = parse_crs(value)
    return bool(parsed is not None and parsed.is_projected)


def units_are_metres(value: object) -> bool:
    """True when every axis of the CRS is expressed in metres."""
    parsed = parse_crs(value)
    if parsed is None or not parsed.axis_info:
        return False
    return all(axis.unit_name.lower() in _METRE_UNITS for axis in parsed.axis_info)


def is_web_mercator(value: object) -> bool:
    """True for EPSG:3857 and friends, which distort distance and area."""
    parsed = parse_crs(value)
    if parsed is None:
        return False
    epsg = parsed.to_epsg()
    if epsg is not None and epsg in _WEB_MERCATOR_EPSGS:
        return True
    return "pseudo-mercator" in parsed.name.lower()


def utm_epsg_for(longitude: float, latitude: float) -> int:
    """Return the WGS 84 UTM EPSG code covering a longitude/latitude position.

    ``UTM zone = floor((longitude + 180) / 6) + 1``, with the northern
    hemisphere using ``EPSG:326xx`` and the southern hemisphere ``EPSG:327xx``.
    """
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        raise ValueError("longitude and latitude must be finite numbers")

    # Normalise into [-180, 180) so out-of-range longitudes still map to a
    # valid zone (1..60).
    normalised = math.fmod(longitude + 180.0, 360.0) - 180.0
    zone = math.floor((normalised + 180.0) / 6.0) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if latitude >= 0 else 32700) + zone


def utm_zone_label(epsg: int) -> str:
    """Human readable label for a UTM EPSG code, e.g. ``UTM zone 44N``."""
    zone = epsg % 100
    hemisphere = "N" if epsg < 32700 else "S"
    return f"UTM zone {zone}{hemisphere}"


def representative_lonlat(
    gdf: gpd.GeoDataFrame, source_crs: CRS | None = None
) -> tuple[float, float] | None:
    """Centre of the dataset bounds expressed as WGS 84 lon/lat.

    Returns ``None`` when the dataset is empty, has non-finite bounds or has
    no usable CRS to transform from.
    """
    if len(gdf) == 0:
        return None
    min_x, min_y, max_x, max_y = (float(value) for value in gdf.total_bounds)
    if not all(math.isfinite(value) for value in (min_x, min_y, max_x, max_y)):
        return None

    centre_x = (min_x + max_x) / 2.0
    centre_y = (min_y + max_y) / 2.0

    crs = parse_crs(source_crs if source_crs is not None else gdf.crs)
    if crs is None:
        return None
    if crs.is_geographic:
        return centre_x, centre_y

    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(centre_x, centre_y)
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return None
    return float(lon), float(lat)


def build_plan(gdf: gpd.GeoDataFrame) -> CrsPlan:
    """Decide which CRS measurements of ``gdf`` should be computed in.

    The strategy, in order:

    1. No usable CRS -> measurements are unavailable (never guess EPSG:4326).
    2. Geographic source -> automatically select the WGS 84 UTM zone that
       covers the centre of the dataset.
    3. Projected source that is metre-based, covers the data and is not Web
       Mercator -> use it as-is (no pointless transformation).
    4. Anything else (Web Mercator, feet, wrong area of use) -> fall back to
       the automatically selected UTM zone.
    """
    source = parse_crs(gdf.crs)
    source_label = crs_label(source)

    if source is None:
        return CrsPlan(
            source_crs=None,
            measurement_crs=None,
            strategy=MeasurementStrategy.UNAVAILABLE,
            is_geographic=False,
            is_projected=False,
            reason=(
                "The file does not declare a coordinate reference system, "
                "so measurements cannot be computed reliably."
            ),
        )

    position = representative_lonlat(gdf, source)
    if position is None:
        return CrsPlan(
            source_crs=source_label,
            measurement_crs=None,
            strategy=MeasurementStrategy.UNAVAILABLE,
            is_geographic=source.is_geographic,
            is_projected=source.is_projected,
            reason="The dataset has no features to derive a measurement CRS from.",
        )

    lon, lat = position

    if source.is_geographic:
        epsg = utm_epsg_for(lon, lat)
        return CrsPlan(
            source_crs=source_label,
            measurement_crs=f"EPSG:{epsg}",
            strategy=MeasurementStrategy.AUTO_UTM,
            is_geographic=True,
            is_projected=False,
            reason=(
                f"Geographic CRS in degrees: measured in EPSG:{epsg} "
                f"({utm_zone_label(epsg)}) covering the dataset centre "
                f"({lon:.4f}, {lat:.4f})."
            ),
        )

    if _is_suitable_projected(source, lon, lat):
        return CrsPlan(
            source_crs=source_label,
            measurement_crs=source_label,
            strategy=MeasurementStrategy.SOURCE_PROJECTED,
            is_geographic=False,
            is_projected=True,
            reason=(
                "The source is already a projected CRS in metres that covers "
                "the data, so no transformation is needed."
            ),
        )

    epsg = utm_epsg_for(lon, lat)
    return CrsPlan(
        source_crs=source_label,
        measurement_crs=f"EPSG:{epsg}",
        strategy=MeasurementStrategy.AUTO_UTM,
        is_geographic=False,
        is_projected=True,
        reason=f"{_unsuitable_reason(source)} Measured in EPSG:{epsg} ({utm_zone_label(epsg)}).",
    )


def _is_suitable_projected(crs: CRS, lon: float, lat: float) -> bool:
    """A projected source is usable when it is metric, covers the data and is
    not the distorting Web Mercator pseudo-projection."""
    if is_web_mercator(crs):
        return False
    if not units_are_metres(crs):
        return False
    return _covers_position(crs, lon, lat)


def _covers_position(crs: CRS, lon: float, lat: float) -> bool:
    """Check whether a lon/lat position lies inside the CRS area of use."""
    area = crs.area_of_use
    if area is None:
        return True
    if area.west <= area.east:
        inside_longitude = area.west <= lon <= area.east
    else:  # area of use crosses the antimeridian
        inside_longitude = lon >= area.west or lon <= area.east
    return inside_longitude and area.south <= lat <= area.north


def _unsuitable_reason(crs: CRS) -> str:
    if is_web_mercator(crs):
        return "Web Mercator inflates distances and areas, so it is not used for measurement."
    if not units_are_metres(crs):
        return f"The source CRS uses {crs.axis_info[0].unit_name} instead of metres."
    return "The data lies outside the area of use of the source projected CRS."
