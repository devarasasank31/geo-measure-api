"""Routes for uploading and reading geospatial files."""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.models.schemas import FileUploadResponse
from app.services import file_service

router = APIRouter(prefix="/api/files", tags=["files"])

_UPLOAD_RESPONSES = {
    400: {
        "description": "The file was rejected (unsupported type, empty or corrupt content).",
        "content": {
            "application/json": {
                "example": {
                    "error": {
                        "code": "UNSUPPORTED_FILE_TYPE",
                        "message": "Only KML files and ZIP archives containing Shapefiles are supported.",
                    }
                }
            }
        },
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
}


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=201,
    summary="Upload a geospatial file",
    description=(
        "Accepts a KML file or a ZIP archive containing a Shapefile "
        "(``.shp``/``.shx``/``.dbf``). The file is validated, stored under a "
        "generated id and processed synchronously."
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
