"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# The season length every historical season is normalized to.
TARGET_RACES = 24


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_path: Path = REPO_ROOT / "data" / "f1.db"
    raw_dir: Path = REPO_ROOT / "data" / "raw"

    # Where the Ergast CSV dump lives (1950-2024).
    csv_dir: Path = Path("C:/Users/thoma/F1_points_application")

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"

    @property
    def sync_db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"


settings = Settings()
