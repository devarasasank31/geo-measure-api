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


def test_conflicting_entries_fail_cleanly(tmp_path: Path) -> None:
    """A member that collides with an earlier file/dir cannot crash extraction."""
    archive_path = build_zip(
        tmp_path / "conflict.zip",
        {"nested": b"file first", "nested/layer.shp": b"then a child"},
    )
    target = tmp_path / "out"

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, target)

    assert excinfo.value.code == "UNSAFE_ARCHIVE"
    assert "Traceback" not in excinfo.value.message
    assert not target.exists()


def test_damaged_member_reports_corrupt_archive(tmp_path: Path) -> None:
    """A CRC mismatch during streaming is reported, not leaked as an OSError."""
    archive_path = tmp_path / "damaged.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("survey.shp", b"SURVEY-PAYLOAD-" * 16)

    raw = bytearray(archive_path.read_bytes())
    offset = raw.find(b"SURVEY-PAYLOAD-")
    assert offset != -1
    raw[offset + 8] ^= 0xFF
    archive_path.write_bytes(bytes(raw))

    with pytest.raises(AppException) as excinfo:
        zip_service.extract_shapefile_archive(archive_path, tmp_path / "out")

    assert excinfo.value.code == "CORRUPT_ARCHIVE"
    assert not (tmp_path / "out").exists()


def test_hostile_upload_filenames_stay_inside_upload_dir(
    client, app_settings: Settings, fixtures_dir: Path, upload_bytes
) -> None:
    """Traversal, absolute and over-long names never influence storage paths."""
    data = (fixtures_dir / "sample.kml").read_bytes()
    hostile_names = [
        "..\\..\\evil.kml",
        "/etc/passwd.kml",
        "a/b/c/../escape.kml",
        "x" * 300 + ".kml",
    ]

    for name in hostile_names:
        response = upload_bytes(data, name)
        assert response.status_code == 201, (name, response.text)
        assert response.json()["filename"]  # sanitised, never empty

    stored_files = [path for path in app_settings.upload_dir.rglob("*") if path.is_file()]
    assert stored_files
    assert all(path.is_relative_to(app_settings.upload_dir) for path in stored_files)
    assert not (app_settings.upload_dir.parent / "evil.kml").exists()
    assert not (app_settings.upload_dir.parent / "escape.kml").exists()
