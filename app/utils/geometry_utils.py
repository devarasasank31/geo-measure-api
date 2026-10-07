"""Helpers shared by anything that inspects Shapely geometries."""

from __future__ import annotations

from typing import Any

#: Geometry type reported for a missing (null) geometry.
NULL_GEOMETRY_TYPE = "Null"


def geometry_type_of(geometry: Any) -> str:
    """Return the GeoJSON/Shapely geometry type, or ``Null`` when absent."""
    geom_type = getattr(geometry, "geom_type", None)
    return geom_type if isinstance(geom_type, str) else NULL_GEOMETRY_TYPE
