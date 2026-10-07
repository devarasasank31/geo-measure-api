"""Persistence operations for uploaded file records.

Kept deliberately small: a handful of explicit functions over one table.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.db.database import db_connection
from app.models.schemas import FileStatus

#: Columns that ``update_record`` is allowed to modify.
UPDATABLE_COLUMNS = frozenset(
    {
        "feature_count",
        "source_crs",
        "measurement_crs",
        "measurement_strategy",
        "status",
        "error_message",
        "features_json",
        "measurements_json",
    }
)


@dataclass(slots=True)
class FileRecord:
    """Database representation of one uploaded file."""

    filename: str
    format: str
    stored_path: str
    size_bytes: int
    id: str = ""
    feature_count: int = 0
    source_crs: str | None = None
    measurement_crs: str | None = None
    measurement_strategy: str | None = None
    status: FileStatus = FileStatus.PROCESSING
    error_message: str | None = None
    features_json: str | None = None
    measurements_json: str | None = None
    created_at: str = ""

    @classmethod
    def new(
        cls,
        *,
        id: str,
        filename: str,
        format: str,
        stored_path: str,
        size_bytes: int,
        status: FileStatus = FileStatus.PROCESSING,
    ) -> "FileRecord":
        return cls(
            id=id,
            filename=filename,
            format=format,
            stored_path=stored_path,
            size_bytes=size_bytes,
            status=status,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    @property
    def features(self) -> list[dict]:
        return json.loads(self.features_json) if self.features_json else []

    @property
    def measurements(self) -> list[dict]:
        return json.loads(self.measurements_json) if self.measurements_json else []


def _row_to_record(row: "tuple | object") -> FileRecord:
    values = dict(row)  # type: ignore[arg-type]
    values["status"] = FileStatus(values["status"])
    return FileRecord(**values)


def insert_record(record: FileRecord) -> FileRecord:
    """Persist a new file record and return it."""
    values = asdict(record)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    with db_connection() as connection:
        connection.execute(
            f"INSERT INTO files ({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        )
    return record


def get_record(file_id: str) -> FileRecord | None:
    """Fetch a record by id, or ``None`` when it does not exist."""
    with db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM files WHERE id = ?", (file_id,)
        ).fetchone()
    return _row_to_record(row) if row else None


def update_record(file_id: str, **fields_values: object) -> None:
    """Update the given whitelisted columns of a record."""
    invalid = set(fields_values) - UPDATABLE_COLUMNS
    if invalid:
        raise ValueError(f"Cannot update columns: {sorted(invalid)}")
    if not fields_values:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields_values)
    with db_connection() as connection:
        connection.execute(
            f"UPDATE files SET {assignments} WHERE id = ?",
            (*fields_values.values(), file_id),
        )
