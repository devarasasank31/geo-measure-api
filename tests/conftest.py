"""Shared pytest fixtures.

Every test gets an isolated upload directory and SQLite database, so tests
never touch real application data.
"""

from __future__ import annotations

import io
import itertools
import zipfile
from pathlib import Path
from typing import Callable

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from app.core.config import Settings, get_settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def app_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Return application settings redirected to a temporary directory."""
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "data" / "geomeasure_test.db")
    return settings


@pytest.fixture()
def client(app_settings: Settings) -> TestClient:
    """FastAPI test client bound to a freshly created application."""
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture()
def sample_kml(fixtures_dir: Path) -> Path:
    """Path to the committed multi-geometry sample KML."""
    return fixtures_dir / "sample.kml"


@pytest.fixture()
def make_shapefile_zip(tmp_path: Path) -> Callable[..., Path]:
    """Factory that writes a GeoDataFrame to disk as a zipped Shapefile."""
    counter = itertools.count()

    def _make(gdf: gpd.GeoDataFrame, archive_name: str | None = None) -> Path:
        index = next(counter)
        work_dir = tmp_path / f"shp_{index}"
        work_dir.mkdir()
        gdf.to_file(work_dir / "dataset.shp")
        archive = tmp_path / (archive_name or f"dataset_{index}.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for part in sorted(work_dir.iterdir()):
                zf.write(part, arcname=part.name)
        return archive

    return _make


@pytest.fixture()
def shapefile_zip(make_shapefile_zip: Callable[..., Path]) -> Path:
    """A deterministic two-polygon Shapefile archive in EPSG:4326."""
    gdf = gpd.GeoDataFrame(
        {"name": ["North Field", "South Field"], "code": [101, 102]},
        geometry=[box(78.40, 17.30, 78.41, 17.31), box(78.42, 17.32, 78.43, 17.33)],
        crs="EPSG:4326",
    )
    return make_shapefile_zip(gdf, "fields.zip")


@pytest.fixture()
def make_zip_bytes() -> Callable[..., bytes]:
    """Build ZIP archive bytes entirely in memory."""

    def _make(entries: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        return buffer.getvalue()

    return _make


@pytest.fixture()
def upload_path(client: TestClient) -> Callable[..., object]:
    """Upload a file from disk and return the raw response."""

    def _upload(
        path: Path,
        filename: str | None = None,
        content_type: str = "application/octet-stream",
    ):
        return client.post(
            "/api/files/",
            files={"file": (filename or path.name, path.read_bytes(), content_type)},
        )

    return _upload


@pytest.fixture()
def upload_bytes(client: TestClient) -> Callable[..., object]:
    """Upload in-memory bytes and return the raw response."""

    def _upload(data: bytes, filename: str, content_type: str = "application/octet-stream"):
        return client.post(
            "/api/files/",
            files={"file": (filename, data, content_type)},
        )

    return _upload
