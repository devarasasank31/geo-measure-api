"""Convert geospatial Python objects into JSON-safe values.

Everything the API returns must survive ``json.dumps``: Shapely geometries,
NumPy scalars, ``NaN`` and ``NaT`` all need explicit handling.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry
from shapely.geometry import mapping as shapely_mapping

NULL_LIKE = object()


def is_null(value: Any) -> bool:
    """True for ``None``, ``NaN``, ``NaT`` and other missing markers."""
    if value is None or value is pd.NaT:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(result, (bool, np.bool_)):
        return bool(result)
    return False


def json_safe(value: Any) -> Any:
    """Recursively convert ``value`` into something ``json.dumps`` accepts."""
    if value is NULL_LIKE:
        return None
    if value is None:
        return None
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, (str, int)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if is_null(value):
        return None
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [json_safe(item) for item in value]
    return str(value)


def geometry_to_geojson(geometry: BaseGeometry | None) -> dict[str, Any] | None:
    """Return a GeoJSON-style mapping for a Shapely geometry."""
    if geometry is None:
        return None
    return json_safe(shapely_mapping(geometry))


def properties_to_dict(properties: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a feature's attributes to a JSON-safe dict.

    Missing values (``None``/``NaN``/``NaT``) are dropped instead of being
    emitted as ``NaN``, which would produce invalid JSON.
    """
    result: dict[str, Any] = {}
    for key, value in properties.items():
        if key == "geometry" or is_null(value):
            continue
        result[str(key)] = json_safe(value)
    return result
