"""ZIP extraction security tests (Zip Slip, limits, shapefile detection)."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.exceptions import AppException
from app.services import zip_service


def build_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_extracts_valid_archive_and_locates_shapefile(tmp_path: Path) -> None:
    archive_path = build_zip(
        tmp_path / "valid.zip",
        {"survey.shp": b"shp", "survey.shx": b"shx", "survey.dbf": b"dbf"},
    )

    result = zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert result.shapefile_path == tmp_path / "out" / "survey.shp"
    assert result.entry_count == 3
    assert (tmp_path / "out" / "survey.shp").read_bytes() == b"shp"


def test_finds_shapefile_in_a_subdirectory(tmp_path: Path) -> None:
    archive_path = build_zip(
        tmp_path / "nested.zip",
        {"layers/parcel.shp": b"shp", "layers/parcel.dbf": b"dbf"},
    )

    result = zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert result.shapefile_path == tmp_path / "out" / "layers" / "parcel.shp"


def test_rejects_zip_slip_path_traversal(tmp_path: Path) -> None:
    archive_path = build_zip(tmp_path / "evil.zip", {"../evil.txt": b"pwned"})
    target = tmp_path / "out"

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, target)

    assert excinfo.value.code == "UNSAFE_ARCHIVE"
    assert not (tmp_path / "evil.txt").exists()
    assert not (target / "evil.txt").exists()


def test_rejects_deep_path_traversal(tmp_path: Path) -> None:
    archive_path = build_zip(tmp_path / "evil.zip", {"a/../../evil.txt": b"pwned"})

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "UNSAFE_ARCHIVE"
    assert not (tmp_path / "evil.txt").exists()


def test_rejects_absolute_path(tmp_path: Path) -> None:
    archive_path = build_zip(tmp_path / "abs.zip", {"/etc/evil.txt": b"pwned"})

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "UNSAFE_ARCHIVE"


def test_rejects_windows_drive_path(tmp_path: Path) -> None:
    archive_path = build_zip(tmp_path / "drive.zip", {"C:/windows/evil.txt": b"pwned"})

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "UNSAFE_ARCHIVE"


def test_rejects_symlink_entry(tmp_path: Path) -> None:
    archive_path = tmp_path / "link.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo("sneaky-link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "UNSAFE_ARCHIVE"


def test_rejects_too_many_entries(
    tmp_path: Path, app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_settings, "max_zip_entries", 2)
    archive_path = build_zip(
        tmp_path / "many.zip",
        {f"file{i}.txt": b"x" for i in range(3)},
    )

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "ARCHIVE_LIMIT_EXCEEDED"


def test_rejects_extreme_compression_ratio(tmp_path: Path) -> None:
    """A small archive that expands enormously is refused (zip bomb)."""
    archive_path = build_zip(tmp_path / "bomb.zip", {"bomb.shp": b"\x00" * (2 * 1024 * 1024)})

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "ARCHIVE_LIMIT_EXCEEDED"


def test_rejects_archive_expanding_beyond_limit(
    tmp_path: Path, app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_settings, "max_extract_mb", 1)
    archive_path = tmp_path / "stored.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("big.shp", b"x" * (2 * 1024 * 1024))

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "ARCHIVE_LIMIT_EXCEEDED"


def test_rejects_archive_without_shapefile(tmp_path: Path) -> None:
    archive_path = build_zip(tmp_path / "docs.zip", {"readme.txt": b"hello"})

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "NO_SHAPEFILE_IN_ARCHIVE"
    assert not (tmp_path / "out" / "readme.txt").exists()


def test_rejects_corrupt_archive(tmp_path: Path) -> None:
    archive_path = tmp_path / "corrupt.zip"
    archive_path.write_bytes(b"PK\x03\x04 but not really a zip")

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "CORRUPT_ARCHIVE"


def test_only_allowed_paths_are_written(tmp_path: Path) -> None:
    archive_path = build_zip(
        tmp_path / "mixed.zip",
        {"ok.shp": b"a", "nested/ok.dbf": b"b", "nested/deep/ok.shx": b"c"},
    )
    target = tmp_path / "out"

    zip_service.extract_shapefile_archive(archive_path, target)

    written = sorted(
        str(path.relative_to(target)).replace("\\", "/") for path in target.rglob("*") if path.is_file()
    )
    assert written == ["nested/deep/ok.shx", "nested/ok.dbf", "ok.shp"]
