"""Coordinate reference system detection, selection and transformation.

Measurements must never be computed on longitude/latitude degrees: one
degree of latitude is roughly 111 km, and one degree of longitude shrinks
towards the poles, so ``geometry.area`` on geographic coordinates returns
meaningless "square degrees". This module decides which projected CRS is
suitable for a dataset and transforms geometries into it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from pyproj import CRS
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
