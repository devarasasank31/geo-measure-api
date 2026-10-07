"""Upload validation, storage, processing and record lifecycle."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import AppException
from app.db import repository
from app.db.repository import FileRecord
from app.models.schemas import FileStatus
from app.services import (
    crs_service,
    geospatial_service,
    measurement_service,
    zip_service,
)
from app.utils import file_utils

logger = logging.getLogger(__name__)

_READ_CHUNK_BYTES = 1024 * 1024
_EXTRACTED_DIRNAME = "extracted"


async def handle_upload(upload: UploadFile) -> FileRecord:
    """Validate, store, register and process an uploaded file.

    Raises :class:`AppException` for any input the API refuses; in that case
    nothing is left behind on disk. Processing failures persist a ``FAILED``
    record before the clean API error is returned.
    """
    record = await store_upload(upload)
    await process_stored_file(record.id)
    return _reload(record.id)


async def store_upload(upload: UploadFile) -> FileRecord:
    """Validate an upload and stream it to controlled storage."""
    extension = file_utils.validate_extension(upload.filename, settings.allowed_extensions)
    filename = file_utils.sanitize_filename(upload.filename)
    file_id = file_utils.generate_file_id()
    destination = file_utils.storage_path(file_id, extension)

    try:
        size_bytes = await _stream_to_disk(upload, destination)
        _validate_content(destination, extension)
    except AppException:
        file_utils.delete_storage(file_id)
        raise

    record = repository.insert_record(
        FileRecord.new(
            id=file_id,
            filename=filename,
            format=extension.lstrip("."),
            stored_path=str(destination),
            size_bytes=size_bytes,
            status=FileStatus.PROCESSING,
        )
    )
    logger.info(
        "Stored upload id=%s filename=%s format=%s bytes=%d",
        record.id,
        record.filename,
        record.format,
        record.size_bytes,
    )
    return record


async def process_stored_file(file_id: str) -> None:
    """Run the CPU/IO-bound processing pipeline off the event loop."""
    try:
        await run_in_threadpool(process_record, file_id)
    except AppException as exc:
        repository.update_record(
            file_id, status=FileStatus.FAILED, error_message=exc.message
        )
        logger.warning("Processing failed for %s: %s (%s)", file_id, exc.code, exc.message)
        raise
    except Exception as exc:  # unexpected failure: log it, hide it from clients
        logger.exception("Unexpected processing failure for %s", file_id)
        repository.update_record(
            file_id,
            status=FileStatus.FAILED,
            error_message="The file could not be processed.",
        )
        raise AppException(
            "PROCESSING_FAILED",
            "The file could not be processed.",
            status_code=422,
        ) from exc


def process_record(file_id: str) -> None:
    """Parse a stored file, extract its features and persist the outcome."""
    record = repository.get_record(file_id)
    if record is None:
        raise AppException("FILE_NOT_FOUND", "Unknown file id.", status_code=404)

    try:
        gdf = _load_dataset(record)
        features = geospatial_service.build_features(gdf)
        source_crs = geospatial_service.crs_label(gdf)

        # CRS plan first: measurements are only ever computed in a metric CRS.
        plan = crs_service.build_plan(gdf)
        logger.info("CRS plan for %s: %s", record.filename, plan.reason)
        measured_gdf = crs_service.transform_for_measurement(gdf, plan)
        measurements = measurement_service.compute_measurements(gdf, measured_gdf, plan)

        repository.update_record(
            file_id,
            feature_count=len(features),
            source_crs=source_crs,
            measurement_crs=plan.measurement_crs,
            measurement_strategy=plan.strategy.value,
            features_json=json.dumps([feature.model_dump() for feature in features]),
            measurements_json=json.dumps(
                [measurement.model_dump(mode="json") for measurement in measurements]
            ),
            status=FileStatus.COMPLETED,
            error_message=None,
        )
        logger.info(
            "Processed %s: %d feature(s), source CRS %s, measurement CRS %s",
            record.filename,
            len(features),
            source_crs,
            plan.measurement_crs,
        )
    finally:
        # Temporary extraction output is never needed again after processing.
        zip_service.cleanup_directory(_extraction_dir(record))


def _load_dataset(record: FileRecord) -> gpd.GeoDataFrame:
    """Read the stored upload into a GeoDataFrame for its format."""
    path = Path(record.stored_path)
    if record.format == "kml":
        return geospatial_service.read_kml(path)
    if record.format == "zip":
        archive = zip_service.extract_shapefile_archive(path, _extraction_dir(record))
        return geospatial_service.read_shapefile(archive.shapefile_path)
    raise AppException(
        "UNSUPPORTED_FILE_TYPE",
        "Only KML files and ZIP archives containing Shapefiles are supported.",
        status_code=400,
    )


def _extraction_dir(record: FileRecord) -> Path:
    return Path(record.stored_path).parent / _EXTRACTED_DIRNAME


def _reload(file_id: str) -> FileRecord:
    record = repository.get_record(file_id)
    if record is None:
        logger.error("Record %s disappeared after processing", file_id)
        raise AppException(
            "PROCESSING_FAILED",
            "The file could not be processed.",
            status_code=422,
        )
    return record


def _validate_content(path: Path, extension: str) -> None:
    """Cheap content sniffing so obviously wrong payloads fail early.

    The extension only tells us what the client claims the file is; this
    check verifies the first bytes agree before anything tries to parse it.
    """
    if extension == ".zip" and not file_utils.looks_like_zip(path):
        raise AppException(
            "CORRUPT_ARCHIVE",
            "The uploaded file is not a valid ZIP archive.",
            status_code=400,
        )
    if extension == ".kml" and not file_utils.looks_like_xml(path):
        raise AppException(
            "INVALID_FILE_CONTENT",
            "The uploaded file does not look like a KML/XML document.",
            status_code=400,
        )


async def _stream_to_disk(upload: UploadFile, destination: Path) -> int:
    """Write the upload in chunks, enforcing size limits while streaming."""
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.max_upload_bytes:
                raise AppException(
                    "FILE_TOO_LARGE",
                    f"Uploaded file exceeds the {settings.max_upload_mb} MB limit.",
                    status_code=413,
                )
            handle.write(chunk)

    if total == 0:
        raise AppException(
            "EMPTY_FILE",
            "The uploaded file is empty.",
            status_code=400,
        )
    return total
