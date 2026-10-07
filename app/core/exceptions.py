"""Structured API errors and FastAPI exception handlers.

Every error leaving the API has the same shape:

.. code-block:: json

    {"error": {"code": "UNSUPPORTED_FILE_TYPE", "message": "..."}}

Stack traces are never returned to clients; they are logged server side.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

#: Fallback messages for framework-level HTTP errors.
_HTTP_CODE_NAMES: dict[int, str] = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "UNPROCESSABLE_ENTITY",
    500: "INTERNAL_ERROR",
}


class AppException(Exception):
    """Domain error that maps to a consistent JSON error response."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def error_payload(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_payload(code, message))


def _validation_message(exc: RequestValidationError) -> str:
    """Build a readable message from FastAPI/pydantic validation errors."""
    parts: list[str] = []
    for err in exc.errors()[:5]:
        location = ".".join(str(item) for item in err.get("loc", ()) if item != "body")
        message = str(err.get("msg", "invalid value"))
        parts.append(f"{location}: {message}" if location else message)
    return "Request validation failed: " + "; ".join(parts)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the global exception handlers to the application."""

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "%s %s -> %s (%s)",
            request.method,
            request.url.path,
            exc.code,
            exc.message,
        )
        return error_response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("%s %s -> validation error", request.method, request.url.path)
        return error_response("VALIDATION_ERROR", _validation_message(exc), 422)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _HTTP_CODE_NAMES.get(exc.status_code, f"HTTP_{exc.status_code}")
        detail: Any = exc.detail
        message = detail if isinstance(detail, str) and detail else "Request failed."
        return error_response(code, message, exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled error while processing %s %s", request.method, request.url.path
        )
        return error_response(
            "INTERNAL_ERROR", "An unexpected error occurred.", 500
        )
