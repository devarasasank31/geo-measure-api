"""Pydantic response/request models shared across the API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FileStatus(str, Enum):
    """Lifecycle state of an uploaded file record."""

    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeasurementStatus(str, Enum):
    """Outcome of the measurement attempt for one feature."""

    COMPLETED = "COMPLETED"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"
    CRS_MISSING = "CRS_MISSING"
    NULL_GEOMETRY = "NULL_GEOMETRY"
    ERROR = "ERROR"


class HealthResponse(BaseModel):
    """Payload returned by ``GET /health``."""

    status: str


class Feature(BaseModel):
    """One feature of an uploaded file, serialised for JSON responses."""

    feature_id: int = Field(..., description="Zero-based index of the feature in the source file")
    geometry_type: str = Field(..., description="GeoJSON geometry type, e.g. Polygon or LineString")
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON-style geometry in the source CRS"
    )
    crs: str | None = Field(default=None, description="CRS of the source coordinates, e.g. EPSG:4326")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Feature attributes, JSON-safe"
    )


class Measurement(BaseModel):
    """Measurement result for a single feature."""

    feature_id: int
    geometry_type: str
    measurement: float | None = Field(default=None, description="Area in m² or length in m")
    measurement_unit: str | None = Field(default=None, description="m² or m when measured")
    status: MeasurementStatus
    detail: str | None = Field(
        default=None, description="Explanation shown when the status is not COMPLETED"
    )


class FileUploadResponse(BaseModel):
    """Payload returned by ``POST /api/files/``."""

    id: str
    filename: str
    feature_count: int
    crs: str | None
    status: FileStatus


class FileInfoResponse(FileUploadResponse):
    """Payload returned by ``GET /api/files/{id}/``."""

    format: str
    size_bytes: int
    measurement_crs: str | None
    measurement_strategy: str | None
    created_at: datetime
    error: str | None = None
    features: list[Feature] = Field(
        default_factory=list,
        description="Every feature with its geometry, properties and CRS",
    )


class MeasurementsResponse(BaseModel):
    """Payload returned by ``GET /api/files/{id}/measurements/``."""

    file_id: str
    source_crs: str | None
    measurement_crs: str | None
    measurement_strategy: str | None
    measurements: list[Measurement]

