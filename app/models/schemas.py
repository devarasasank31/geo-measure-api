"""Pydantic response/request models shared across the API."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FileStatus(str, Enum):
    """Lifecycle state of an uploaded file record."""

    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


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


class FileUploadResponse(BaseModel):
    """Payload returned by ``POST /api/files/``."""

    id: str
    filename: str
    feature_count: int
    crs: str | None
    status: FileStatus

