"""Reading vector datasets and turning their rows into API features."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd

from app.core.exceptions import AppException
from app.models.schemas import Feature
from app.utils.serialization import geometry_to_geojson, properties_to_dict

logger = logging.getLogger(__name__)

#: Engines tried (in order) when reading a vector file.
_READ_ENGINES = ("pyogrio", "fiona")

_PARSE_ERROR_MESSAGE = "The file could not be parsed as a geospatial dataset."


@dataclass(slots=True)
class ParsedDataset:
    """A parsed vector file ready for feature extraction and measurement."""

    gdf: gpd.GeoDataFrame
    features: list[Feature]
    source_crs: str | None


def crs_label(gdf: gpd.GeoDataFrame) -> str | None:
    """Return the dataset CRS in ``EPSG:xxxx`` form, or ``None`` if missing."""
    if gdf.crs is None:
        return None
    return gdf.crs.to_string()


def read_shapefile(shapefile_path: Path) -> gpd.GeoDataFrame:
    """Read a ``.shp`` file (with its sidecars) into a GeoDataFrame."""
    return _read_vector(shapefile_path)


def read_kml(kml_path: Path) -> gpd.GeoDataFrame:
    """Read a KML file into a GeoDataFrame.

    The OGC KML specification defines coordinates as WGS 84 longitude/latitude,
    and GDAL reports ``EPSG:4326`` for valid files.

    A well-formed KML that simply contains no features is returned as an empty
    GeoDataFrame instead of being reported as a parse failure.
    """
    _enable_fiona_kml_drivers()
    try:
        return _read_vector(kml_path)
    except AppException:
        if _is_featureless_kml(kml_path):
            logger.info("KML %s is well-formed but contains no features", kml_path.name)
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        raise


#: KML element names that carry actual feature data.
_KML_FEATURE_TAGS = frozenset({"Placemark", "GroundOverlay", "Model"})


def _is_featureless_kml(path: Path) -> bool:
    """True when the file is well-formed XML without any KML features."""
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError, ValueError):
        return False
    for element in tree.iter():
        tag = element.tag
        if isinstance(tag, str) and tag.rsplit("}", 1)[-1] in _KML_FEATURE_TAGS:
            return False
    return True


def _enable_fiona_kml_drivers() -> None:
    """Fiona ships with KML support disabled; enable it for the fallback path."""
    from fiona import drvsupport

    drvsupport.supported_drivers.setdefault("KML", "rw")
    drvsupport.supported_drivers.setdefault("LIBKML", "rw")


def build_features(gdf: gpd.GeoDataFrame) -> list[Feature]:
    """Convert every row of a GeoDataFrame into a JSON-safe feature."""
    source_crs = crs_label(gdf)
    features: list[Feature] = []
    for position in range(len(gdf)):
        row = gdf.iloc[position]
        geometry = row.geometry
        properties = row.drop(labels="geometry") if "geometry" in row.index else row
        features.append(
            Feature(
                feature_id=position,
                geometry_type=_geometry_type(geometry),
                geometry=geometry_to_geojson(geometry),
                crs=source_crs,
                properties=properties_to_dict(properties),
            )
        )
    logger.debug("Extracted %d features (source CRS: %s)", len(features), source_crs)
    return features


def _geometry_type(geometry: object) -> str:
    geom_type = getattr(geometry, "geom_type", None)
    return geom_type if isinstance(geom_type, str) else "Null"


def _read_vector(path: Path, driver: str | None = None) -> gpd.GeoDataFrame:
    """Read a vector file, trying each supported engine in turn."""
    errors: list[str] = []
    for engine in _READ_ENGINES:
        try:
            options: dict[str, str] = {"engine": engine}
            if driver is not None:
                options["driver"] = driver
            gdf = gpd.read_file(path, **options)
        except Exception as exc:  # engines raise driver-specific exceptions
            errors.append(f"{engine}: {exc}")
            logger.debug("Reading %s with %s failed: %s", path.name, engine, exc)
            continue
        logger.info(
            "Read %s with %s: %d feature(s), CRS %s",
            path.name,
            engine,
            len(gdf),
            crs_label(gdf),
        )
        return gdf

    logger.warning("All read engines failed for %s: %s", path.name, " | ".join(errors))
    raise AppException("MALFORMED_INPUT", _PARSE_ERROR_MESSAGE, status_code=422)
