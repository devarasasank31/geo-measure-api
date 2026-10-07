"""Upload validation, storage and record lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import AppException
from app.db import repository
from app.db.repository import FileRecord
from app.models.schemas import FileStatus
from app.utils import file_utils

logger = logging.getLogger(__name__)

_READ_CHUNK_BYTES = 1024 * 1024


async def handle_upload(upload: UploadFile) -> FileRecord:
    """Validate, store and register an uploaded file.

    Raises :class:`AppException` for any input the API refuses; in that case
    nothing is left behind on disk.
    """
    record = await store_upload(upload)
    return record


async def store_upload(upload: UploadFile) -> FileRecord:
    """Validate an upload and stream it to controlled storage."""
    extension = file_utils.validate_extension(upload.filename, settings.allowed_extensions)
    filename = file_utils.sanitize_filename(upload.filename)
    file_id = file_utils.generate_file_id()
    destination = file_utils.storage_path(file_id, extension)

    try:
        size_bytes = await _stream_to_disk(upload, destination)
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
            status=FileStatus.COMPLETED,
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
