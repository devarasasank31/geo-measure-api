"""SQLite connection management and schema initialisation."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id                 TEXT PRIMARY KEY,
    filename           TEXT NOT NULL,
    format             TEXT NOT NULL,
    stored_path        TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    feature_count      INTEGER NOT NULL DEFAULT 0,
    source_crs         TEXT,
    measurement_crs    TEXT,
    measurement_strategy TEXT,
    status             TEXT NOT NULL,
    error_message      TEXT,
    features_json      TEXT,
    measurements_json  TEXT,
    created_at         TEXT NOT NULL
);
"""


def _open_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def db_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a connection, committing on success and always closing it."""
    connection = _open_connection(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create the database schema if it does not exist yet."""
    with db_connection() as connection:
        connection.executescript(SCHEMA)
