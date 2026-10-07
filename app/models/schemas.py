"""Pydantic response/request models shared across the API."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class FileStatus(str, Enum):
    """Lifecycle state of an uploaded file record."""

    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class HealthResponse(BaseModel):
    """Payload returned by ``GET /health``."""

    status: str
