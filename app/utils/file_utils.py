"""Validation and safety helpers for uploaded files.

Uploaded filenames and archives are untrusted input: nothing here ever
trusts a path supplied by the client.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.core.exceptions import AppException

#: Characters kept in display filenames; everything else collapses to ``_``.
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LENGTH = 120

_ZIP_MAGIC_NUMBERS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def generate_file_id() -> str:
    """Return a unique, filesystem-safe identifier for an upload."""
    return uuid.uuid4().hex


def sanitize_filename(filename: str | None) -> str:
    """Reduce an untrusted filename to a safe basename for display.

    Any directory components (``/``, ``\\``) are dropped, unsafe characters
    are replaced and the result is truncated to a sane length. The value is
    never used to build a storage path.
    """
    if not filename:
        return "upload"
    basename = re.split(r"[\\/]", filename)[-1]
    basename = _UNSAFE_NAME_CHARS.sub("_", basename).strip("._")
    if not basename:
        return "upload"
    if len(basename) > _MAX_FILENAME_LENGTH:
        suffix = "".join(Path(basename).suffixes[-2:])[:16]
        basename = basename[: _MAX_FILENAME_LENGTH - len(suffix)] + suffix
    return basename


def file_extension(filename: str | None) -> str:
    """Return the lowercase extension of an untrusted filename."""
    return Path(sanitize_filename(filename)).suffix.lower()


def validate_extension(filename: str | None, allowed: Iterable[str]) -> str:
    """Return the validated extension or raise a 400 error."""
    extension = file_extension(filename)
    if extension not in set(allowed):
        raise AppException(
            "UNSUPPORTED_FILE_TYPE",
            "Only KML files and ZIP archives containing Shapefiles are supported.",
            status_code=400,
        )
    return extension


def storage_path(file_id: str, extension: str) -> Path:
    """Return ``uploads/<id>/source<ext>``, creating the directory.

    Paths are built exclusively from a server-generated id and a validated
    extension, so an uploaded filename can never influence where data is
    written.
    """
    root = settings.upload_dir.resolve()
    target_dir = (root / file_id).resolve()
    if not target_dir.is_relative_to(root):
        raise AppException(
            "INVALID_PATH",
            "Refusing to write outside the upload directory.",
            status_code=400,
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"source{extension}"


def delete_storage(file_id: str) -> None:
    """Remove the storage directory of an upload (best effort)."""
    root = settings.upload_dir.resolve()
    target_dir = (root / file_id).resolve()
    if not target_dir.is_relative_to(root) or target_dir == root:
        return
    import shutil

    shutil.rmtree(target_dir, ignore_errors=True)


def looks_like_zip(path: Path) -> bool:
    """Cheap magic-number check for a ZIP archive."""
    try:
        with path.open("rb") as handle:
            header = handle.read(4)
    except OSError:
        return False
    return header in _ZIP_MAGIC_NUMBERS


def looks_like_xml(path: Path) -> bool:
    """Cheap check that a file starts like an XML/KML document."""
    try:
        with path.open("rb") as handle:
            header = handle.read(512)
    except OSError:
        return False
    header = header.lstrip(b"\xef\xbb\xbf \t\r\n")
    return header.startswith(b"<")
