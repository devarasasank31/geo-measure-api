"""Secure extraction of uploaded ZIP archives.

Archives are untrusted input. Entries may attempt path traversal (Zip Slip),
absolute paths, drive-letter paths, symlinks or decompression bombs. Every
member is validated before a single byte is written, and extraction is
bounded by configurable limits.
"""

from __future__ import annotations

import logging
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

#: Path components that are never allowed inside an archive.
_FORBIDDEN_PARTS = frozenset({"..", ""})
_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
_COPY_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ExtractedArchive:
    """Result of a successful, verified extraction."""

    root: Path
    shapefile_path: Path
    entry_count: int


def extract_shapefile_archive(zip_path: Path, target_dir: Path) -> ExtractedArchive:
    """Safely extract ``zip_path`` into ``target_dir`` and locate the ``.shp``.

    Raises :class:`AppException` with a clean API error for corrupt,
    unsafe or oversized archives.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        logger.warning("Invalid ZIP archive %s: %s", zip_path, exc)
        raise AppException(
            "CORRUPT_ARCHIVE",
            "The uploaded archive is not a valid ZIP file.",
            status_code=400,
        ) from exc

    with archive:
        entries = archive.infolist()
        _check_entry_limits(entries)
        # Validate every member name before a single byte is written, then
        # require a Shapefile, then extract.
        members = _validate_members(entries)
        _require_shapefile_entry(entries)
        try:
            entry_count = _extract_members(archive, members, target_dir)
        except AppException:
            cleanup_directory(target_dir)
            raise
        except zipfile.BadZipFile as exc:
            cleanup_directory(target_dir)
            logger.warning("Archive %s is damaged: %s", zip_path, exc)
            raise AppException(
                "CORRUPT_ARCHIVE",
                "The uploaded archive is damaged and could not be read.",
                status_code=400,
            ) from exc
        except OSError as exc:
            cleanup_directory(target_dir)
            logger.warning("Archive %s could not be extracted: %s", zip_path, exc)
            raise AppException(
                "UNSAFE_ARCHIVE",
                "The archive contains conflicting or unwritable entries.",
                status_code=400,
            ) from exc

    shapefile_path = _locate_shapefile(target_dir)
    logger.info(
        "Extracted %d entries from %s (shapefile: %s)",
        entry_count,
        zip_path.name,
        shapefile_path.name,
    )
    return ExtractedArchive(
        root=target_dir,
        shapefile_path=shapefile_path,
        entry_count=entry_count,
    )


def _check_entry_limits(entries: Iterable[zipfile.ZipInfo]) -> None:
    """Reject archives that exceed entry-count or compression-ratio limits."""
    entries = list(entries)
    if len(entries) > settings.max_zip_entries:
        raise AppException(
            "ARCHIVE_LIMIT_EXCEEDED",
            f"The archive contains more than {settings.max_zip_entries} entries.",
            status_code=400,
        )

    total_declared = 0
    for info in entries:
        if info.is_dir():
            continue
        total_declared += info.file_size
        if info.flag_bits & 0x1:  # encrypted entry
            raise AppException(
                "UNSAFE_ARCHIVE",
                "Encrypted archive entries are not supported.",
                status_code=400,
            )
        if _is_symlink(info):
            raise AppException(
                "UNSAFE_ARCHIVE",
                "The archive contains a symbolic link, which is not allowed.",
                status_code=400,
            )
        if info.compress_size and info.file_size:
            ratio = info.file_size / info.compress_size
            if ratio > settings.max_compression_ratio and info.compress_type != zipfile.ZIP_STORED:
                raise AppException(
                    "ARCHIVE_LIMIT_EXCEEDED",
                    "The archive has an extreme compression ratio.",
                    status_code=400,
                )

    if total_declared > settings.max_extract_bytes:
        raise AppException(
            "ARCHIVE_LIMIT_EXCEEDED",
            f"The archive expands beyond {settings.max_extract_mb} MB.",
            status_code=400,
        )


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _require_shapefile_entry(entries: Iterable[zipfile.ZipInfo]) -> None:
    """Fail before writing anything when no ``.shp`` member exists."""
    for info in entries:
        if not info.is_dir() and info.filename.lower().endswith(".shp"):
            return
    raise AppException(
        "NO_SHAPEFILE_IN_ARCHIVE",
        "The ZIP archive does not contain a Shapefile (.shp).",
        status_code=400,
    )


def _member_parts(name: str) -> list[str]:
    """Validate one archive member name and return its safe path components.

    Rejects absolute paths, drive letters, and any ``..`` component so that
    an entry can never escape the extraction directory (Zip Slip).
    """
    if not name or "\x00" in name:
        raise AppException(
            "UNSAFE_ARCHIVE",
            "The archive contains an invalid file name.",
            status_code=400,
        )
    if name.startswith(("/", "\\")) or _DRIVE_PATTERN.match(name):
        raise AppException(
            "UNSAFE_ARCHIVE",
            "The archive contains an absolute path, which is not allowed.",
            status_code=400,
        )
    parts = [part for part in re.split(r"[\\/]+", name) if part != "."]
    if any(part in _FORBIDDEN_PARTS for part in parts):
        raise AppException(
            "UNSAFE_ARCHIVE",
            "The archive contains a path that would escape the extraction directory.",
            status_code=400,
        )
    if not parts:
        raise AppException(
            "UNSAFE_ARCHIVE",
            "The archive contains an invalid file name.",
            status_code=400,
        )
    return parts


def _validate_members(entries: Iterable[zipfile.ZipInfo]) -> list[tuple[zipfile.ZipInfo, list[str]]]:
    """Validate every file entry name before anything is written."""
    members: list[tuple[zipfile.ZipInfo, list[str]]] = []
    for info in entries:
        if info.is_dir():
            continue
        members.append((info, _member_parts(info.filename)))
    return members


def _extract_members(
    archive: zipfile.ZipFile,
    members: list[tuple[zipfile.ZipInfo, list[str]]],
    target_dir: Path,
) -> int:
    """Extract pre-validated members while enforcing the real extracted size."""
    root = target_dir.resolve()
    extracted = 0
    written_total = 0

    for info, parts in members:
        destination = target_dir.joinpath(*parts)
        if not destination.resolve().is_relative_to(root):
            raise AppException(
                "UNSAFE_ARCHIVE",
                "The archive contains a path that would escape the extraction directory.",
                status_code=400,
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        remaining = settings.max_extract_bytes - written_total
        written_total += _copy_member(archive, info, destination, remaining)
        extracted += 1
    return extracted


def _copy_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    max_bytes: int,
) -> int:
    """Stream one member to disk, aborting as soon as the budget runs out."""
    written = 0
    if max_bytes <= 0:
        raise AppException(
            "ARCHIVE_LIMIT_EXCEEDED",
            "The archive expands beyond the configured extraction limit.",
            status_code=400,
        )
    with archive.open(info) as source, destination.open("wb") as handle:
        while True:
            chunk = source.read(_COPY_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                raise AppException(
                    "ARCHIVE_LIMIT_EXCEEDED",
                    "The archive expands beyond the configured extraction limit.",
                    status_code=400,
                )
            handle.write(chunk)
    return written


def _locate_shapefile(root: Path) -> Path:
    """Find the ``.shp`` inside an extracted archive."""
    candidates = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".shp"),
        key=lambda path: (len(path.relative_to(root).parts), str(path).lower()),
    )
    if not candidates:
        raise AppException(
            "NO_SHAPEFILE_IN_ARCHIVE",
            "The ZIP archive does not contain a Shapefile (.shp).",
            status_code=400,
        )

    chosen = candidates[0]
    if len(candidates) > 1:
        logger.warning(
            "Archive contains %d shapefiles; using %s",
            len(candidates),
            chosen.relative_to(root),
        )

    siblings = {path.suffix.lower() for path in chosen.parent.iterdir() if path.is_file()}
    missing = [suffix for suffix in (".shx", ".dbf") if suffix not in siblings]
    if missing:
        logger.warning(
            "Shapefile %s is missing sidecar file(s): %s",
            chosen.name,
            ", ".join(missing),
        )
    return chosen


def cleanup_directory(directory: Path | None) -> None:
    """Best-effort removal of a controlled working directory."""
    if directory is None:
        return
    shutil.rmtree(directory, ignore_errors=True)
