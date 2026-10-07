"""Routes for uploading and reading geospatial files."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, UploadFile

from app.models.schemas import Feature, FileInfoResponse, FileUploadResponse
from app.services import file_service

router = APIRouter(prefix="/api/files")

_ERROR_EXAMPLE = {
    "error": {
        "code": "UNSUPPORTED_FILE_TYPE",
        "message": "Only KML files and ZIP archives containing Shapefiles are supported.",
    }
}
_NOT_FOUND_EXAMPLE = {
    "error": {"code": "FILE_NOT_FOUND", "message": "No file was found with the given id."}
}

_UPLOAD_RESPONSES = {
    400: {
        "description": "The file was rejected (unsupported type, empty or corrupt content).",
        "content": {"application/json": {"example": _ERROR_EXAMPLE}},
    },
    413: {
        "description": "The uploaded file exceeds the configured size limit.",
        "content": {
            "application/json": {
                "example": {
                    "error": {"code": "FILE_TOO_LARGE", "message": "Uploaded file exceeds the 50 MB limit."}
                }
            }
        },
    },
    422: {
        "description": "The file was stored but could not be parsed or processed.",
        "content": {
            "application/json": {
                "example": {
                    "error": {"code": "MALFORMED_INPUT", "message": "The file could not be parsed as a geospatial dataset."}
                }
            }
        },
    },
}
_NOT_FOUND_RESPONSES = {
    404: {
        "description": "No file exists with the given id.",
        "content": {"application/json": {"example": _NOT_FOUND_EXAMPLE}},
    },
}


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=201,
    tags=["files"],
    summary="Upload a geospatial file",
    description=(
        "Accepts a KML file or a ZIP archive containing a Shapefile "
        "(``.shp``/``.shx``/``.dbf``). The file is validated, stored under a "
        "generated id, parsed and measured synchronously."
    ),
    responses=_UPLOAD_RESPONSES,
)
async def upload_file(
    file: UploadFile = File(..., description="KML file or ZIP archive containing a Shapefile"),
) -> FileUploadResponse:
    record = await file_service.handle_upload(file)
    return FileUploadResponse(
        id=record.id,
        filename=record.filename,
        feature_count=record.feature_count,
        crs=record.source_crs,
        status=record.status,
    )


@router.get(
    "/{file_id}/",
    response_model=FileInfoResponse,
    tags=["files"],
    summary="Get file information",
    description=(
        "Returns the stored metadata, CRS decisions and every extracted "
        "feature (geometry, properties, CRS) for one uploaded file."
    ),
    responses=_NOT_FOUND_RESPONSES,
)
def get_file(file_id: str) -> FileInfoResponse:
    record = file_service.load_record_or_404(file_id)
    return FileInfoResponse(
        id=record.id,
        filename=record.filename,
        feature_count=record.feature_count,
        crs=record.source_crs,
        status=record.status,
        format=record.format,
        size_bytes=record.size_bytes,
        measurement_crs=record.measurement_crs,
        measurement_strategy=record.measurement_strategy,
        created_at=datetime.fromisoformat(record.created_at),
        error=record.error_message,
        features=[Feature.model_validate(item) for item in record.features],
    )
