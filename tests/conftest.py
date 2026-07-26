from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.core.config import settings

#: Tests that assert against the real historical record need the built database.
#: They skip rather than fail when it is absent, so a fresh clone can still run
#: the pure-simulation tests without a 2-minute build step.
requires_db = pytest.mark.skipif(
    not settings.db_path.exists(),
    reason="data/f1.db not built — run scripts/build_db.py",
)


@pytest.fixture(scope="session")
def db_engine():
    if not settings.db_path.exists():
        pytest.skip("data/f1.db not built")
    engine = create_engine(settings.sync_db_url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    with db_engine.connect() as conn:
        yield conn


def scalar(conn, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


@pytest.fixture(scope="session")
def csv_dir() -> Path:
    if not settings.csv_dir.exists():
        pytest.skip(f"Ergast CSV dump not found at {settings.csv_dir}")
    return settings.csv_dir
