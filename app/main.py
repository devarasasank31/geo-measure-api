"""FastAPI application factory for GeoMeasure API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.routes import files, health
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.database import init_db

logger = logging.getLogger(__name__)

OPENAPI_TAGS = [
    {"name": "health", "description": "Liveness and readiness probes."},
    {"name": "files", "description": "Upload geospatial files and read their features."},
    {
        "name": "measurements",
        "description": "CRS-aware area and length measurements per feature.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare storage directories and the database on startup."""
    setup_logging(settings.log_level)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("%s v%s started", settings.app_name, settings.app_version)
    yield
    logger.info("%s stopped", settings.app_name)


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Upload KML files or ZIP archives containing a Shapefile, extract "
            "their features, detect the coordinate reference system and compute "
            "CRS-aware measurements (polygon area, line length)."
        ),
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(files.router)
    return app


app = create_app()
