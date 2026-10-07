"""Application configuration.

All runtime knobs live here so that no module has to read environment
variables or hardcode paths on its own.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Project root (the directory that contains ``app/``).
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings, sourced from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "GeoMeasure API"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"

    # Storage (relative paths resolve against the project root)
    upload_dir: Path = BASE_DIR / "uploads"
    db_path: Path = BASE_DIR / "data" / "geo_measure.db"

    # Upload and archive safety limits
    max_upload_mb: int = Field(default=50, ge=1, le=4096)
    max_extract_mb: int = Field(default=256, ge=1, le=16384)
    max_zip_entries: int = Field(default=1000, ge=1, le=100000)
    max_compression_ratio: float = Field(default=500.0, ge=1.0)

    # Output formatting
    measurement_decimals: int = Field(default=2, ge=0, le=6)

    @field_validator("upload_dir", "db_path", mode="before")
    @classmethod
    def _resolve_relative_paths(cls, value: object) -> object:
        if isinstance(value, str):
            path = Path(value)
            if not path.is_absolute():
                path = BASE_DIR / path
            return path
        return value

    @property
    def allowed_extensions(self) -> tuple[str, ...]:
        """File extensions accepted by the upload endpoint."""
        return (".kml", ".zip")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_extract_bytes(self) -> int:
        return self.max_extract_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()


#: Shared settings object. Tests mutate attributes on this instance so that
#: every module observes the same values.
settings = get_settings()
